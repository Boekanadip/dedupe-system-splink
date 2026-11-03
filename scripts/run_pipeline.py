"""Auto-pipeline: CSV → Standardize → Splink → PostgreSQL → API."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.standardize import standardize
from src.splink_model import train_and_predict
from scripts.batch_predict import main as batch_predict_main


def run_pipeline(csv_path: str = None, columns: list[str] | None = None, max_pairs: int = 10_000, sample_size: int | None = None):
    """
    Full auto-pipeline:
    1. CSV → Standardize
    2. Standardized → Splink Model → Predictions
    3. Predictions → PostgreSQL
    4. Reload API
    """
    print("=" * 60)
    print("CRM Entity Resolution - Auto Pipeline")
    print("=" * 60)
    
    # Default CSV path
    if csv_path is None:
        csv_path = PROJECT_ROOT / "data" / "raw" / "batch_0001.csv"
    else:
        csv_path = Path(csv_path)
    
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        return False
    
    # Step 1: Standardize
    print("\n[1/4] Standardizing data...")
    try:
        import pandas as pd
        df_raw = pd.read_csv(csv_path)
        
        if sample_size and len(df_raw) > sample_size:
            print(f"    Sampling {sample_size} rows from {len(df_raw)} total...")
            df_raw = df_raw.sample(n=sample_size, random_state=42)
        
        df_std = standardize(df_raw)
        standardized_path = PROJECT_ROOT / "data" / "processed" / "crm_standardized.parquet"
        standardized_path.parent.mkdir(parents=True, exist_ok=True)
        df_std.to_parquet(standardized_path)
        print(f"    OK Standardized: {standardized_path}")
    except Exception as e:
        print(f"    ERROR Standardization failed: {e}")
        return False
    
    # Step 2: Splink prediction
    print("\n[2/4] Running Splink model...")
    try:
        import pandas as pd
        from src.config import atomic_write_parquet

        df = pd.read_parquet(standardized_path)
        pred_df, _linker = train_and_predict(
            df,
            selected_columns=columns,
            max_pairs=max_pairs,
        )
        out_path = PROJECT_ROOT / "outputs" / "splink_predictions.parquet"
        atomic_write_parquet(pred_df, out_path)
        predictions_path = out_path
        print(f"    OK Predictions: {predictions_path}")
    except Exception as e:
        print(f"    ERROR Splink prediction failed: {e}")
        return False
    
    # Step 3: Save to PostgreSQL
    print("\n[3/4] Saving to PostgreSQL...")
    try:
        batch_predict_main()
        print("    OK Saved to PostgreSQL")
    except Exception as e:
        print(f"    ERROR PostgreSQL save failed: {e}")
        return False
    
    # Step 4: Reload API (simulated)
    print("\n[4/4] Pipeline complete!")
    print("    → API will serve new predictions on next request")
    
    print("\n" + "=" * 60)
    print("Pipeline completed successfully!")
    print("=" * 60)
    print("\nNext steps:")
    print("  • API: http://localhost:8000")
    print("  • UI:  http://localhost:8501")
    print("  • Run: curl -X POST http://localhost:8000/api/reload")
    
    return True


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="CRM auto-pipeline: CSV → standardize → Splink → Postgres.")
    ap.add_argument("csv", nargs="?", default=None, help="Path to raw CSV (default: bundled sample).")
    ap.add_argument("--columns", default=None, help="Comma-separated columns for dynamic matching.")
    ap.add_argument("--max-pairs", type=int, default=10_000, dest="max_pairs")
    ap.add_argument("--sample", type=int, default=None, help="Sample N rows from CSV (default: use all)")
    ns = ap.parse_args()

    cols = [c.strip() for c in ns.columns.split(",")] if ns.columns else None
    success = run_pipeline(ns.csv, columns=cols, max_pairs=ns.max_pairs, sample_size=ns.sample)
    sys.exit(0 if success else 1)