import psycopg2
import pandas as pd

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="crm",
    user="crm_user",
    password="crm_password_2026",
)

# Daftar tabel yang mau dilihat
tables = [
    "splink_data.customers",
    "splink_data.processed_customers", 
    "splink_data.dedup_outputs",
    "splink_data.master_customer_current",
    "splink_data.master_customer_bersih",
    "splink_data.entity_map",
    "splink_data.gold_labels",
]

print("=" * 60)
print("LIHAT DATA TABEL POSTGRESQL")
print("=" * 60)

for t in tables:
    try:
        df = pd.read_sql_query(f"SELECT * FROM {t} LIMIT 20", conn)
        print(f"\n📊 {t}")
        print("-" * 60)
        print(df.to_string(index=False))
        print(f"... (menampilkan 20 dari {df.shape[0]} baris)")
    except Exception as e:
        print(f"\n❌ {t}: ERROR - {e}")

# Bonus: Distribusi di dedup_outputs
print("\n" + "=" * 60)
print("📈 Distribusi di dedup_outputs (SEMUA BARIS)")
print("=" * 60)
df_all = pd.read_sql_query("""
    SELECT decision, COUNT(*) as cnt
    FROM splink_data.dedup_outputs
    GROUP BY decision
    ORDER BY decision
""", conn)
print(df_all.to_string(index=False))

conn.close()