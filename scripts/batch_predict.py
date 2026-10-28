"""Batch prediction: Load parquet → classify → save to PostgreSQL."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values

from src.db import get_connection

THRESHOLD_MATCH = 0.95
THRESHOLD_NON_MATCH = 0.01

def main():
    print("=" * 50)
    print("CRM Entity Resolution - Batch Prediction")
    print("=" * 50)
    
    # Step 1: Load predictions from parquet
    parquet_path = PROJECT_ROOT / "outputs" / "splink_predictions.parquet"
    print(f"Loading predictions from: {parquet_path}")
    if not parquet_path.exists():
        print("❌ Predictions parquet not found!")
        return
    
    df = pd.read_parquet(parquet_path)
    print(f"Loaded {len(df)} predictions")
    
    # Step 2: Classify based on thresholds
    print(f"\nClassifying with thresholds: MATCH>{THRESHOLD_MATCH}, NON_MATCH<={THRESHOLD_NON_MATCH}")
    df['match_status'] = 'REVIEW'
    match_count = 0
    non_match_count = 0
    review_count = 0
    
    for idx, row in df.iterrows():
        prob = row['match_probability']
        if prob >= THRESHOLD_MATCH:
            df.at[idx, 'match_status'] = 'MATCH'
            match_count += 1
        elif prob <= THRESHOLD_NON_MATCH:
            df.at[idx, 'match_status'] = 'NON_MATCH'
            non_match_count += 1
        else:
            df.at[idx, 'match_status'] = 'REVIEW'
            review_count += 1
    
    print(f"MATCH: {match_count:,}")
    print(f"REVIEW: {review_count:,}")
    print(f"NON_MATCH: {non_match_count:,}")
    
    # Step 3: Save to database tables
    print("\nSaving to database...")
    
    # Save to customer_matches
    records_df = df[['record_id_l', 'record_id_r', 'match_probability', 'match_status']].copy()
    records_df.rename(columns={'record_id_l': 'customer_id_1', 'record_id_r': 'customer_id_2'}, inplace=True)
    records = records_df.values.tolist()
    
    print(f"Saving {len(records)} records to splink_data.customer_matches...")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            execute_values(cursor, """
                INSERT INTO splink_data.customer_matches 
                (customer_id_1, customer_id_2, match_probability, match_status)
                VALUES %s
                ON CONFLICT (customer_id_1, customer_id_2) DO UPDATE SET
                    match_probability = EXCLUDED.match_probability,
                    match_status = EXCLUDED.match_status
            """, records)
            conn.commit()
    print(f"[OK] Saved {len(records)} predictions to splink_data.customer_matches")
    
    # Save to review queue
    review_df = df[df['match_status'] == 'REVIEW']
    if len(review_df) > 0:
        queue_df = review_df[['record_id_l', 'record_id_r', 'match_probability']].copy()
        queue_df.rename(columns={'record_id_l': 'customer_id_1', 'record_id_r': 'customer_id_2'}, inplace=True)
        queue_records = queue_df.values.tolist()
        
        print(f"Saving {len(queue_records)} records to splink_data.review_queue...")
        with get_connection() as conn:
            with conn.cursor() as cursor:
                execute_values(cursor, """
                    INSERT INTO splink_data.review_queue 
                    (customer_id_1, customer_id_2, match_probability)
                    VALUES %s
                """, queue_records)
                conn.commit()
        print(f"[OK] Saved {len(queue_records)} pairs to splink_data.review_queue")
    
    # Print summary
    print("\n" + "=" * 50)
    print("PREDICTION SUMMARY")
    print("=" * 50)
    print(f"Total pairs: {len(df):,}")
    print(f"MATCH (>=0.95): {match_count:,}")
    print(f"REVIEW ({THRESHOLD_NON_MATCH}-{THRESHOLD_MATCH}): {review_count:,}")
    print(f"NON_MATCH (<0.01): {non_match_count:,}")
    print("=" * 50)

if __name__ == "__main__":
    main()