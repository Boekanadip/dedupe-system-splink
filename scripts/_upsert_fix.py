import pandas as pd, psycopg2, sys
sys.path.insert(0, '.')
from src.standardize import normalize_date
from src.persist import _upsert, get_connection, qualified, key_sql, action

conn = psycopg2.connect(host='localhost', port=5432, dbname='crm',
                        user='crm_user', password='crm_password_2026')
conn.autocommit = False

# Baca semua record
df = pd.read_sql('SELECT record_id, dob_std FROM splink_data.processed_customers', conn)
df['record_id'] = df.record_id.astype(str)
print('total records:', len(df))

# Terapkan fix
def fix_dob(d):
    if pd.isna(d) or str(d).strip().lower() in ('none', 'nan', ''):
        return None
    try:
        dt = pd.to_datetime(str(d), errors='coerce')
        if pd.isna(dt):
            return None
        if dt.day > 12:
            swapped = pd.Timestamp(year=dt.year, month=dt.day, day=dt.month)
            if swapped.day <= 12:
                return swapped.date()
        return dt.date()
    except Exception:
        return None

df['dob_std_fixed'] = df.dob_std.apply(fix_dob)
null_before = df.dob_std.isna().sum()
null_after = df.dob_std_fixed.isna().sum()
print(f'NULL before fix: {null_before}, after fix: {null_after}')
print(f'Records with changed dob: {(df.dob_std != df.dob_std_fixed.astype(str)).sum()}')

# Persist kembali menggunakan mekanisme upsert dari persist.py
# Hanya kolom yang dibutuhkan
keep = ["record_id", "customer_id", "source", "first_name_std", "last_name_std",
        "email_std", "phone_std", "address_std", "city_std", "state_std",
        "country_std", "dob_std_fixed"]
frame = df[[c for c in keep if c in df.columns]].copy()
frame["record_id"] = frame["record_id"].astype(str)

# Konversi dob yang sudah fix ke date dengan dayfirst=True (seperti persist_processed)
if "dob_std_fixed" in frame.columns:
    frame["dob_std"] = pd.to_datetime(
        frame["dob_std_fixed"].astype(str), dayfirst=True, errors="coerce"
    ).dt.date

print('Records to upsert:', len(frame))

# Drop tabel lama dan upsert (tidak ada ON CONFLICT yang ideal, coba update per-record)
# Gunakan pendekatan: update per record_id
updated = 0
skipped = 0
with conn.cursor() as cur:
    for _, row in frame.iterrows():
        rid = str(row['record_id'])
        dob = row['dob_std']
        if dob is None:
            cur.execute(
                f"UPDATE {qualified('splink_data.processed_customers')} SET dob_std = NULL WHERE record_id = %s",
                (rid,),
            )
        else:
            cur.execute(
                f"UPDATE {qualified('splink_data.processed_customers')} SET dob_std = %s WHERE record_id = %s",
                (dob, rid),
            )
        updated += cur.rowcount
    conn.commit()

print(f'Updated: {updated} records')

# Verify
verify = pd.read_sql('SELECT record_id, dob_std FROM splink_data.processed_customers LIMIT 10', conn)
print('Verify sample:')
print(verify.to_string())
conn.close()