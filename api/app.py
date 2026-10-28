"""FastAPI application for CRM entity resolution predictions."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

app = FastAPI(title="CRM Entity Resolution API")

PREDICTIONS_PATH = PROJECT_ROOT / "outputs" / "splink_predictions.parquet"

# Load predictions once
_predictions_df = None

def get_predictions():
    global _predictions_df
    if _predictions_df is None and PREDICTIONS_PATH.exists():
        _predictions_df = pd.read_parquet(PREDICTIONS_PATH)
    return _predictions_df

@app.get("/api/stats")
def stats():
    """Get statistics."""
    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="No predictions found")
    
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)