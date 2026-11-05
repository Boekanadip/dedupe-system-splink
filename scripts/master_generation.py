"""Master customer generation: entity_id → single master record."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from src.db import get_connection
from psycopg2.extras import execute_values


def generate_master_customers(entity_map_df: pd.DataFrame, standardized_df: pd.DataFrame) -> pd.DataFrame:
    """Generate master customer dari entity clusters - optimized."""
    if len(entity_map_df) == 0:
        print("No entity mappings found")
        return pd.DataFrame()
    
    # Merge dan hitung completeness dalam satu tahap.
    merged = entity_map_df.merge(standardized_df, on='record_id', how='left')
    source_columns = [
        'first_name_std', 'last_name_std', 'email_std', 'phone_std',
        'address_std', 'city_std', 'state_std', 'country_std', 'dob_std',
    ]
    available = [c for c in source_columns if c in merged.columns]
    
    merged['_completeness'] = merged[available].notna().sum(axis=1)
    # Urutkan: completeness desc, record_id asc.
    merged = merged.sort_values(['entity_id', '_completeness', 'record_id'],
                                ascending=[True, False, True])
    # Ambil baris pertama per entity.
    masters = merged.groupby('entity_id', sort=True).first().reset_index()
    
    # Bangun list source_records per entity.
    source_records = merged.groupby('entity_id')['record_id'].apply(list).to_dict()
    masters['source_records'] = masters['entity_id'].map(source_records)
    
    # Rename dan select kolom.
    masters = masters.rename(columns={
        'record_id': 'source_record_id',
        '_completeness': 'source_completeness'
    })
    keep = ['entity_id', 'first_name_std', 'last_name_std', 'email_std', 'phone_std',
            'address_std', 'city_std', 'state_std', 'country_std', 'dob_std',
            'source_records', 'source_record_id', 'source_completeness']
    masters = masters[[c for c in keep if c in masters.columns]]
    return masters


def save_master_customers_to_db(master_df: pd.DataFrame):
    """Save master customers ke database dengan UPSERT."""
    if len(master_df) == 0:
        print("No master customers to save")
        return
    
    # Konversi list ke string untuk PostgreSQL ARRAY.
    records = []
    for _, row in master_df.iterrows():
        records.append((
            row['entity_id'],
            row.get('first_name_std'),
            row.get('last_name_std'),
            row.get('email_std'),
            row.get('phone_std'),
            row.get('address_std'),
            row.get('city_std'),
            row.get('state_std'),
            row.get('country_std'),
            row.get('dob_std'),
            row.get('source_records', []),
            row.get('source_record_id'),
            int(row.get('source_completeness', 0)),
        ))
    
    print(f"Saving {len(records)} master customers to splink_data.master_customers (UPSERT)...")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            execute_values(cursor, """
                INSERT INTO splink_data.master_customers 
                (entity_id, first_name, last_name, email, phone, address, city, state, country, dob, source_records, source_record_id, source_completeness)
                VALUES %s
                ON CONFLICT (entity_id) DO UPDATE SET
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    email = EXCLUDED.email,
                    phone = EXCLUDED.phone,
                    address = EXCLUDED.address,
                    city = EXCLUDED.city,
                    state = EXCLUDED.state,
                    country = EXCLUDED.country,
                    dob = EXCLUDED.dob,
                    source_records = EXCLUDED.source_records,
                    source_record_id = EXCLUDED.source_record_id,
                    source_completeness = EXCLUDED.source_completeness
            """, records)
            conn.commit()
    print(f"[OK] Saved {len(records)} master customers")


def main():
    print("=" * 60)
    print("Master Customer Generation")
    print("=" * 60)
    
    # Load entity_map
    entity_map_path = PROJECT_ROOT / "outputs" / "entity_map.parquet"
    if not entity_map_path.exists():
        print(f"ERROR: {entity_map_path} not found. Run clustering.py first.")
        return
    
    entity_map = pd.read_parquet(entity_map_path)
    print(f"Loaded {len(entity_map)} entity mappings")
    
    # Load standardized data
    std_path = PROJECT_ROOT / "data" / "processed" / "crm_standardized.parquet"
    if not std_path.exists():
        print(f"ERROR: {std_path} not found")
        return
    
    standardized = pd.read_parquet(std_path)
    print(f"Loaded {len(standardized)} standardized records")
    
    # Generate master customers
    master_customers = generate_master_customers(entity_map, standardized)
    print(f"Generated {len(master_customers)} master customers")
    
    # Save to DB
    save_master_customers_to_db(master_customers)
    
    # Save backup parquet
    backup_path = PROJECT_ROOT / "outputs" / "master_customers.parquet"
    master_customers.to_parquet(backup_path, index=False)
    print(f"[OK] Backup saved: {backup_path}")
    
    print("\n" + "=" * 60)
    print(f"Master customer generation complete: {len(master_customers)} entities")
    print("=" * 60)


if __name__ == "__main__":
    main()
