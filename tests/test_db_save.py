import pandas as pd
import psycopg2

# Konek ke PostgreSQL container
conn = psycopg2.connect(
    host="localhost",
    dbname="crm_db",
    user="postgres",
    password="postgres"
)

# Cek tabel sudah ada apa nggak
cur = conn.cursor()
cur.execute("""
    SELECT table_name FROM information_schema.tables 
    WHERE table_schema = 'public'
""")
tables = cur.fetchall()
print('Tabel di DB:', [t[0] for t in tables])

# Load predictions
pred = pd.read_parquet('outputs/splink_predictions.parquet')
print(f'\nTotal records untuk disimpan: {len(pred)}')

# Coba insert sekup sample 10 baris saja dulu
sample = pred.head(10)
for _, row in sample.iterrows():
    cur.execute("""
        INSERT INTO splink_data.customer_matches 
        (customer_l_id, customer_r_id, match_probability, decision, threshold_used, source_table, matched_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """, (
        str(row["record_id_l"]),
        str(row["record_id_r"]),
        float(row["match_probability"]),
        row["decision"],
        0.86,
        "batch_job"
    ))

conn.commit()
cur.close()
conn.close()
print('\nSample 10 records berhasil disimpan ke PostgreSQL!')
