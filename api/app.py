"""FastAPI application for CRM entity resolution predictions."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import tempfile
import io

from src.export import csv_bytes, save_to_database
from src.splink_model import (build_dynamic_settings_from_columns, 
                             infer_selected_columns_from_df, 
                             add_decision_dynamic,
                             apply_business_rules)
from src.config import (MATCH_THRESHOLD, REVIEW_THRESHOLD, 
                        LAMBDA_RECALL_ASSUMPTION, DETERMINISTIC_RULES)

try:
    from src.config import MATCH_THRESHOLD, REVIEW_THRESHOLD
except Exception:  # config may import heavy deps in some deployments
    MATCH_THRESHOLD, REVIEW_THRESHOLD = 0.84, 0.35

app = FastAPI(title="CRM Entity Resolution API")

# Enable CORS for UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREDICTIONS_PATH = PROJECT_ROOT / "outputs" / "splink_predictions.parquet"
MODEL_PATH = PROJECT_ROOT / "models" / "latest.json"

# Load predictions once
_predictions_df = None

def get_predictions():
    global _predictions_df
    if _predictions_df is None and PREDICTIONS_PATH.exists():
        _predictions_df = pd.read_parquet(PREDICTIONS_PATH)
    return _predictions_df


def reload_predictions():
    """Reload predictions from disk."""
    global _predictions_df
    _predictions_df = None
    return get_predictions()


@app.get("/api/pair/{id1}/{id2}")
def pair_detail(id1: str, id2: str):
    """Get detail for specific pair."""
    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="No predictions found")
    
    mask = (
        (df["record_id_l"] == id1) & (df["record_id_r"] == id2) |
        (df["record_id_l"] == id2) & (df["record_id_r"] == id1)
    )
    row = df[mask]
    if row.empty:
        raise HTTPException(status_code=404, detail="Pair not found")
    
    row = row.iloc[0]
    return JSONResponse({
        "record_id_l": row["record_id_l"],
        "record_id_r": row["record_id_r"],
        "match_probability": float(row["match_probability"]),
        "decision": row["decision"]
    })


@app.post("/api/run-dedup")
def run_dedup(
    selected_columns: list[str] = [],
    scope: str = Query("sample", regex="^(sample|full)$"),
):
    """
    Run deduplication with user-selected columns.
    
    Parameters
    ----------
    selected_columns : list[str]
        List of standard column names chosen by the user for comparison, 
        e.g., ['first_name_std', 'email_std', 'dob_std'].
        Kosongkan jika ingin menggunakan semua kolom standar yang tersedia.
    scope : str
        "sample" (default) untuk 10000 record pertama, "full" untuk seluruh dataset.
    
    Returns
    -------
    JSON response dengan ringkasan hasil deduplication.
    """
    import pandas as pd
    from src.config import PROCESSED_DATA_PATH, OUTPUT_DIR, PREDICTIONS_PATH
    from src import load_data  # helper sederhana
    
    # --- Validasi dan persiapan kolom ---
    # Muat data untuk melihat kolom yang tersedia
    try:
        df_raw = load_data(full=(scope == "full"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memuat data: {e}")
    
    # Dapatkan daftar kolom standar yang valid
    valid_cols = infer_selected_columns_from_df(df_raw)
    
    # Validasi: jika selected_columns kosong, gunakan semua yang valid
    if not selected_columns:
        selected_columns = valid_cols
        info_msg = f"Tidak ada pemilihan kolom. Menggunakan semua {len(selected_columns)} kolom standar yang tersedia."
    else:
        # Filter selected_columns hanya yang valid
        selected_valid = [c for c in selected_columns if c in valid_cols]
        if not selected_valid:
            return JSONResponse({
                "status": "error",
                "message": f"Tidak ada kolom dari {selected_columns} valid untuk pencocokan. "
                           f"Kolom yang tersedia: {', '.join(valid_cols)}"
            }, status_code=400)
        selected_columns = selected_valid
        info_msg = f"Menggunakan {len(selected_columns)} kolom yang dipilih: {', '.join(selected_columns)}"
    
    # --- Build Splink configuration dari kolom yang dipilih ---
    try:
        config = build_dynamic_settings_from_columns(selected_columns)
    except ValueError as ve:
        return JSONResponse({
            "status": "error",
            "message": str(ve)
        }, status_code=400)
    
    # --- Train & Predict dengan konfigurasi dinamis ---
    from splink import DuckDBAPI, Linker, SettingsCreator
    import time
    
    started = time.perf_counter()
    
    # Register data ke DuckDB API
    db_api = DuckDBAPI()
    sdf = db_api.register_table(df_raw)
    
    # Buat Linker dengan konfigurasi dinamis (tanpa training EM ulang jika sudah ada model)
    # Kita gunakan konfigurasi yang baru dibangun, tapi linker akan estimate params-nya
    linker = Linker(sdf, config["comparisons"], blocking_rules=config["blocking_rules"])
    
    # Estimasi parameter menggunakan EM standar pada konfigurasi baru
    # Ini akan mengambil waktu tergantung jumlah pasangan dan kolom yang dipilih
    try:
        linker.training.estimate_u_using_random_sampling(max_pairs=100000, seed=42)
        
        # Estimasi m-probability untuk deterministic rules dan custom comparisons
        # Lakukan pada rules yang sudah dibangun
        for name, rule in []:  # placeholder - diisi oleh rules dari config
            pass
        
        # Estimasi parameter untuk blocking rules
        linker.training.estimate_probability_two_random_records_match(
            DETERMINISTIC_RULES, recall=LAMBDA_RECALL_ASSUMPTION
        )
        
    except Exception as e:
        # Jika gagal estimates (misal data terlalu sedikit), fallback ke konfigurasi default
        import traceback
        traceback.print_exc()
        # Fallback: gunakan settings creator dari konfigurasi lama
        from splink import SettingsCreator
        default_settings = SettingsCreator(
            link_type="dedupe_only",
            unique_id_column_name="record_id",
            comparisons=[...],  # comparisons default
            blocking_rules_to_generate_predictions=[block_on("email_std"), block_on("phone_pre7")],
        )
        linker = Linker(sdf, default_settings)
    
    # Prediksi dan tambahkan decision
    pred_df = add_decision(linker.inference.predict().as_pandas_dataframe())
    pred_df = add_decision_dynamic(pred_df, MATCH_THRESHOLD, REVIEW_THRESHOLD)
    
    # Tambahkan business rules (opsional, tetap pakai kolom standar)
    from src.splink_model import apply_business_rules
    pred_df = apply_business_rules(pred_df, verbose=False)
    
    # Simpan hasil
    out_path = PREDICTIONS_PATH if scope == "full" else (OUTPUT_DIR / "splink_predictions_sample.parquet")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from src.config import atomic_write_parquet
    atomic_write_parquet(pred_df, out_path)
    
    runtime = round(time.perf_counter() - started, 2)
    
    # Hitung statistik
    decisions = pred_df["decision"].value_counts().to_dict()
    total = len(pred_df)
    
    return JSONResponse({
        "status": "success",
        "scope": scope,
        "selected_columns": selected_columns,
        "total_records": len(df_raw),
        "pairs_scored": total,
        "decisions": decisions,
        "match_rate": decisions.get("MATCH", 0) / total if total else 0,
        "review_rate": decisions.get("REVIEW", 0) / total if total else 0,
        "non_match_rate": decisions.get("NON_MATCH", 0) / total if total else 0,
        "runtime_seconds": runtime,
        "message": info_msg,
        "config_summary": {
            "comparisons_count": len(config["comparisons"]),
            "blocking_rules": [r.pattern for r in config["blocking_rules"]] if config["blocking_rules"] else "default"
        }
    })


@app.get("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": pd.Timestamp.utcnow().isoformat(),
        "predictions_loaded": _predictions_df is not None,
        "predictions_count": len(_predictions_df) if _predictions_df is not None else 0,
        "model_path_exists": MODEL_PATH.exists()
    }


@app.get("/api/stats")
def stats():
    """Get statistics."""
    df = get_predictions()
    if df is None:
        return JSONResponse({
            "total_pairs": 0,
            "matches": 0,
            "review": 0,
            "non_matches": 0,
            "avg_probability": 0.0,
            "timestamp": pd.Timestamp.utcnow().isoformat()
        })
    
    return JSONResponse({
        "total_pairs": len(df),
        "matches": int(len(df[df["decision"] == "MATCH"])),
        "review": int(len(df[df["decision"] == "REVIEW"])),
        "non_matches": int(len(df[df["decision"] == "NON_MATCH"])),
        "avg_probability": float(df["match_probability"].mean()),
        "timestamp": pd.Timestamp.utcnow().isoformat()
    })


@app.get("/api/pairs")
def pairs(status: str = Query(None), page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=100)):
    """Get pairs with optional status filter."""
    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="No predictions found")
    
    if status:
        df = df[df["decision"] == status.upper()]
    
    start = (page - 1) * per_page
    end = start + per_page
    
    df_page = df.iloc[start:end]
    return JSONResponse({
        "pairs": df_page[["record_id_l", "record_id_r", "match_probability", "decision"]].to_dict("records"),
        "total": len(df),
        "page": page,
        "per_page": per_page
    })


@app.get("/api/pair/{id1}/{id2}")
def pair_detail(id1: str, id2: str):
    """Get detail for specific pair."""
    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="No predictions found")
    
    mask = (
        (df["record_id_l"] == id1) & (df["record_id_r"] == id2) |
        (df["record_id_l"] == id2) & (df["record_id_r"] == id1)
    )
    row = df[mask]
    if row.empty:
        raise HTTPException(status_code=404, detail="Pair not found")
    
    row = row.iloc[0]
    return JSONResponse({
        "record_id_l": row["record_id_l"],
        "record_id_r": row["record_id_r"],
        "match_probability": float(row["match_probability"]),
        "decision": row["decision"]
    })


@app.get("/api/search")
def search(q: str = Query("", min_length=1)):
    """Search record by ID."""
    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="No predictions found")
    
    if not q:
        return JSONResponse({"results": []})
    
    mask = (df["record_id_l"].str.contains(q, na=False)) | (df["record_id_r"].str.contains(q, na=False))
    results = df[mask].head(20)
    
    return JSONResponse({
        "results": [
            {
                "record_id_l": row["record_id_l"],
                "record_id_r": row["record_id_r"],
                "match_probability": float(row["match_probability"]),
                "decision": row["decision"]
            }
            for _, row in results.iterrows()
        ]
    })


@app.post("/api/batch-predict")
async def batch_predict(file: UploadFile = File(...)):
    """
    Batch predict from CSV/Parquet file.
    Returns match predictions for all pairs in the file.
    """
    # Save uploaded file
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # Load data
        if file.filename.endswith('.parquet'):
            df = pd.read_parquet(tmp_path)
        elif file.filename.endswith('.csv'):
            df = pd.read_csv(tmp_path)
        else:
            raise HTTPException(status_code=400, detail="Only CSV or Parquet files supported")
        
        # Basic validation - check for required columns
        required_cols = ['record_id', 'first_name', 'last_name']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {missing}")
        
        # Return summary (actual prediction would require model loading)
        return JSONResponse({
            "status": "received",
            "records_count": len(df),
            "filename": file.filename,
            "message": "Data received. Run scripts/batch_predict.py for full pipeline."
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@app.post("/api/reload")
def reload():
    """Reload predictions from disk."""
    reload_predictions()
    df = get_predictions()
    return JSONResponse({
        "status": "reloaded",
        "predictions_count": len(df) if df is not None else 0
    })


@app.get("/api/model/info")
def model_info():
    """Get model information."""
    import json
    if not MODEL_PATH.exists():
        return JSONResponse({
            "model_version": None,
            "status": "no_model"
        })
    
    with open(MODEL_PATH) as f:
        model_data = json.load(f)
    
    return JSONResponse({
        "model_version": model_data.get("model_version"),
        "trained_at": model_data.get("trained_at"),
        "threshold_match": model_data.get("threshold_match", 0.84),
        "threshold_review": model_data.get("threshold_review", 0.35),
        "threshold_non_match": model_data.get("threshold_non_match", 0.35),
        "status": "loaded"
    })


@app.get("/api/download")
def download_csv():
    """Download predictions as CSV file."""
    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="No predictions found")
    if "decision" not in df.columns and "match_probability" in df.columns:
        df = df.copy()
        df["decision"] = df["match_probability"].apply(
            lambda p: "MATCH" if p >= MATCH_THRESHOLD
            else ("REVIEW" if p >= REVIEW_THRESHOLD else "NON_MATCH")
        )
    return StreamingResponse(
        io.BytesIO(csv_bytes(df)),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=splink_predictions.csv"},
    )


@app.post("/api/save-outputs")
def save_outputs(data: dict):
    """Persist posted records to a NEW table (never the source tables)."""
    records = data.get("records")
    if not records:
        raise HTTPException(status_code=400, detail="records is empty")
    table = data.get("table", "splink_data.dedup_outputs")
    if not table.replace("_", "").replace(".", "").isalnum():
        raise HTTPException(status_code=400, detail="invalid table name")
    try:
        n = save_to_database(pd.DataFrame(records), table)
    except Exception as e:
        status = 409 if type(e).__name__ == "UniqueViolation" else 500
        raise HTTPException(status_code=status, detail=f"{type(e).__name__}: {e}")
    return JSONResponse({"status": "success", "table": table, "rows": n})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)