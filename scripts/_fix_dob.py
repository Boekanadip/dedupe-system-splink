import pandas as pd, psycopg2, sys
sys.path.insert(0, '.')
from src.standardize import normalize_date

conn = psycopg2.connect(host='localhost', port=5432, dbname='crm',
                        user='crm_user', password='crm_password_2026')
db = pd.read_sql(
    "SELECT record_id, dob_std FROM splink_data.processed_customers WHERE dob_std IS NOT NULL",
    conn,
)
db['record_id'] = db.record_id.astype(str)
print('non-null dob in DB:', len(db))


def fix_dob(d):
    if pd.isna(d) or str(d).strip().lower() in ('none', 'nan', ''):
        return None
    try:
        dt = pd.to_datetime(str(d), errors='coerce')
        if pd.isna(dt):
            return None
        # Jika day > 12, kemungkinan tertukar (dd/mm/yyyy disimpan sebagai mm/dd/yyyy logic)
        if dt.day > 12:
            swapped = pd.Timestamp(year=dt.year, month=dt.day, day=dt.month)
            if swapped.day <= 12:  # valid swap
                return swapped.date()
        return dt.date()
    except Exception:
        return None


db['fixed_dob'] = db.dob_std.apply(fix_dob)
print('fixed non-null:', db.fixed_dob.notna().sum(), '/', len(db))
print('null after fix:', db.fixed_dob.isna().sum(), '/', len(db))

print()
print('sample fixed:')
for i, row in db.head(5).iterrows():
    print(f'  {row.record_id}: original={row.dob_std}, fixed={row.fixed_dob}')

# Cek konsistensi dengan parquet
std = pd.read_parquet('data/processed/crm_standardized.parquet')
std['record_id'] = std.record_id.astype(str)
# Hanya ambil record yang overlap (40k)
overlap_ids = db.record_id.isin(std.record_id)
db_overlap = db[overlap_ids].copy()
merged = db_overlap.set_index('record_id').join(std.set_index('record_id')['dob_std'], how='inner', rsuffix='_parquet')
print()
print('consistency check (DB fixed vs parquet):')
# both columns are date type now
db_dates = pd.to_datetime(merged.fixed_dob, errors='coerce').dt.date
parquet_dates = pd.to_datetime(merged.dob_std, errors='coerce').dt.date
match = (db_dates == parquet_dates).sum()
total = len(merged)
print(f'  match: {match}/{total} ({100*match/total:.1f}%)')
if match < total:
    disc = merged[db_dates != parquet_dates]
    print('  discrepant sample:')
    for i, r in disc.head(3).iterrows():
        print(f'    {r.name}: db_fixed={r.fixed_dob}, parquet={r.dob_std}')

conn.close()