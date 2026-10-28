"""FastAPI application for CRM entity resolution predictions."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import tempfile

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
        "threshold_match": model_data.get("threshold_match", 0.95),
        "threshold_non_match": model_data.get("threshold_non_match", 0.01),
        "status": "loaded"
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)