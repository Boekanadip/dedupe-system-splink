"""Auto-pipeline: CSV → Standardize → Splink → PostgreSQL → API."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.standardize import standardize_csv
from src.splink_model import train_and_predict
from scripts.batch_predict import main as batch_predict_main


def run_pipeline(csv_path: str = None):
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
        csv_path = PROJECT_ROOT / "data" / "raw" / "crm_50000_customers_dirty_v3.csv"
    else:
        csv_path = Path(csv_path)
    
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        return False
    
    # Step 1: Standardize
    print("\n[1/4] Standardizing data...")
    try:
        from src.standardize import standardize
        standardized_path = standardize(str(csv_path))
        print(f"    ✓ Standardized: {standardized_path}")
    except Exception as e:
        print(f"    ✗ Standardization failed: {e}")
        return False
    
    # Step 2: Splink prediction
    print("\n[2/4] Running Splink model...")
    try:
        predictions_path = train_and_predict(str(standardized_path))
        print(f"    ✓ Predictions: {predictions_path}")
    except Exception as e:
        print(f"    ✗ Splink prediction failed: {e}")
        return False
    
    # Step 3: Save to PostgreSQL
    print("\n[3/4] Saving to PostgreSQL...")
    try:
        batch_predict_main()
        print("    ✓ Saved to PostgreSQL")
    except Exception as e:
        print(f"    ✗ PostgreSQL save failed: {e}")
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
    csv_arg = sys.argv[1] if len(sys.argv) > 1 else None
    success = run_pipeline(csv_arg)
    sys.exit(0 if success else 1)