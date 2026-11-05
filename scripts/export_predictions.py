"""Export predictions to CSV or database."""
import argparse
import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import OUTPUT_DIR, PREDICTIONS_SAMPLE_PATH, PREDICTIONS_FULL_PATH


def export_csv(predictions_path: Path, output_path: Path | None = None):
    """Export predictions to CSV."""
    df = pd.read_parquet(predictions_path)
    
    # Select important columns
    cols = [
        "record_id_l", "record_id_r", 
        "match_probability", "match_weight", 
        "decision", "review_status"
    ]
    cols = [c for c in cols if c in df.columns]
    df_export = df[cols].copy()
    
    # Add human-readable columns
    if "email_std_l" in df.columns and "email_std_r" in df.columns:
        df_export["email_l"] = df["email_std_l"]
        df_export["email_r"] = df["email_std_r"]
    if "first_name_std_l" in df.columns and "first_name_std_r" in df.columns:
        df_export["name_l"] = df["first_name_std_l"] + " " + df["last_name_std_l"].fillna("")
        df_export["name_r"] = df["first_name_std_r"] + " " + df["last_name_std_r"].fillna("")
    
    if output_path is None:
        output_path = predictions_path.with_suffix(".csv")
    
    df_export.to_csv(output_path, index=False)
    print(f"CSV exported: {output_path}")
    print(f"  Total rows: {len(df_export)}")
    print(f"  MATCH: {(df_export['decision'] == 'MATCH').sum()}")
    print(f"  REVIEW: {(df_export['decision'] == 'REVIEW').sum()}")
    print(f"  NON_MATCH: {(df_export['decision'] == 'NON_MATCH').sum()}")
    return df_export


def export_to_db(predictions_path: Path, table_name: str = "incremental_predictions"):
    """Export predictions to PostgreSQL."""
    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        print("psycopg2 not installed. Install with: pip install psycopg2-binary")
        return
    
    from src.db import get_connection
    
    df = pd.read_parquet(predictions_path)
    
    # Prepare data for database
    cols = [
        "record_id_l", "record_id_r", 
        "match_probability", "match_weight", 
        "decision", "review_status"
    ]
    cols = [c for c in cols if c in df.columns]
    df_export = df[cols].copy()
    
    # Add timestamp
    from datetime import datetime
    df_export["created_at"] = datetime.now()
    
    conn = get_connection()
    cur = conn.cursor()
    
    # Create table if not exists
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id SERIAL PRIMARY KEY,
            record_id_l VARCHAR(255),
            record_id_r VARCHAR(255),
            match_probability FLOAT,
            match_weight FLOAT,
            decision VARCHAR(50),
            review_status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    
    # Insert data
    data = [
        (r["record_id_l"], r["record_id_r"], r["match_probability"], 
         r["match_weight"], r["decision"], r.get("review_status", "pending"))
        for _, r in df_export.iterrows()
    ]
    
    execute_values(cur, 
        f"INSERT INTO {table_name} (record_id_l, record_id_r, match_probability, match_weight, decision, review_status) VALUES %s",
        data
    )
    
    conn.commit()
    cur.close()
    conn.close()
    print(f"Exported to PostgreSQL table: {table_name}")
    print(f"  Total rows: {len(df_export)}")


def main():
    parser = argparse.ArgumentParser(description="Export predictions to CSV or database.")
    parser.add_argument("--input", type=Path, help="Input parquet file (default: latest predictions)")
    parser.add_argument("--output", type=Path, help="Output CSV file")
    parser.add_argument("--to-csv", action="store_true", help="Export to CSV")
    parser.add_argument("--to-db", action="store_true", help="Export to PostgreSQL")
    parser.add_argument("--table", default="incremental_predictions", help="Table name for DB export")
    parser.add_argument("--sample", action="store_true", help="Use sample predictions")
    
    args = parser.parse_args()
    
    if args.input:
        predictions_path = args.input
    elif args.sample:
        predictions_path = PREDICTIONS_SAMPLE_PATH
    else:
        predictions_path = PREDICTIONS_FULL_PATH
    
    if not predictions_path.exists():
        print(f"File not found: {predictions_path}")
        return
    
    if args.to_csv or (not args.to_db):
        export_csv(predictions_path, args.output)
    
    if args.to_db:
        export_to_db(predictions_path, args.table)


if __name__ == "__main__":
    main()