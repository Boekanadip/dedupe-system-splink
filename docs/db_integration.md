# DB Integration — Cara Pakai

Jalur DB menambah input database tanpa mengubah Splink, blocking, atau standardize.
Data dibaca read-only, diterjemahkan ke nama kolom pipeline, lalu masuk sebagai batch CSV.

## 1. Arsitektur

```
CSV upload ─────┐
                ├→ DB_COLUMN_MAP → format internal yang sama → validasi → standardisasi
DB (SELECT) ────┘                                         → blocking → Splink → entity/master
```

Semua modul downstream hanya baca `data/processed/crm_standardized.parquet`.

## 2. Mapping Kolom

Pipeline kenal nama kolom di `src/config.py` → `COLUMN_MAP.values()`:
`first_name, last_name, email, phone_number, dob, city, state, address, ...`

- DB pakai nama sama → `DB_COLUMN_MAP = {}` (kosong), langsung jalan.
- DB pakai nama beda → isi kamus terjemahan di `src/config.py`:

```python
DB_COLUMN_MAP = {
    "first_nm":  "first_name",
    "e_mail":    "email",
    "telp":      "phone_number",
    "tgl_lahir": "dob",
    "kota":      "city",
}
# kiri = nama di DB, kanan = nama yang dipahami pipeline
```

Dua kolom DB tidak boleh memetakan ke satu target (ditolak dengan SystemExit).

**Verifikasi sebelum isi:**
```sql
SELECT * FROM crm_customers LIMIT 0;  -- lihat nama kolom persis
```

## 3. Perintah

### Generate data sintetik (tanpa DB asli)
```powershell
python scripts/make_synthetic_db.py --rows 2000 --out data/synthetic/crm.duckdb
```

### Insert baru — satu perintah (Fase 2)
```powershell
# via file DuckDB lokal
python -m src.job_run --source data/synthetic/crm.duckdb --table crm_customers

# via Postgres (DSN)
python -m src.job_run --source "postgres://crm_reader:xxx@host:5432/crm" --table crm_customers

# via config file
python -m src.job_run --config config/job.json
```

`job_run` = fetch (watermark) → register batch → `incremental --stage` → `outputs/job_run_summary.json` + exit code.
Watermark hanya maju setelah seluruh job sukses. Re-run = noop, exit 0, tidak double-count.

### Update record yang berubah (Fase 3)
```powershell
python -m src.db_refresh --source "postgres://crm_reader:xxx@host:5432/crm" --table crm_customers --date-order dmy
```
- Butuh `customer_pk` (PK stabil) di tabel. `customer_id` di dataset lama tidak unik, bukan PK.
- Membutuhkan `updated_at` (TIMESTAMP, satu timezone konsisten — semua UTC atau semua lokal).
- `record_id` dipertahankan, `entity_id` TIDAK diubah otomatis. Jika match edge berubah, dicatat di `outputs/db_stale_entities.json` untuk review manusia.

### Export saja (tanpa scoring)
```powershell
python -m src.db_export --source ... --table ... --watermark
```

## 4. Pengembalian Hasil Bersih ke DB (Belum Implement — Proposal)

**Prinsip:** jangan pernah `UPDATE` tabel sumber. Tulis ke tabel terpisah di schema `dedup_results`.

Opsi yang disarankan:

| Tabel | Isi | Kegunaan |
|-------|-----|----------|
| `dedup_results.golden_master` | `entity_id, master_first_name, master_email, ... , record_count, conflicted_fields` | Satu baris per orang — yang dikonsumsi aplikasi lain |
| `dedup_results.entity_map_export` | `record_id, customer_pk, entity_id` | Traceability record → entity |
| `dedup_results.linkage_evidence` | `record_id_l, record_id_r, match_probability, decision, bukti per field` | Audit kenapa dua record digabung |

Alur: `master_customers.parquet` + `entity_map.parquet` → `COPY` ke Postgres (via `src/db_push.py` — akan dibuat jika diminta).

## 5. Halaman Explain untuk Data dari DB

Saat ini:
- `pages/8_explain.py` = bukti per **pasangan** (kenapa dua record dianggap sama).
- `pages/2_master.py` = nilai master per **entity** + record anggota + field konflik.

Untuk DB, yang perlu ditambah:
1. Di `2_master.py`: kolom `customer_pk` + tombol "Export entity ini ke DB" + badge "sumber: DB vs CSV".
2. Di `8_explain.py`: filter by `customer_pk` (selain `record_id`), tampilkan `customer_pk` kedua sisi.
3. Halaman baru `pages/10_db_export.py` (opsional): preview 10 baris `golden_master` + tombol push ke DB dengan konfirmasi.

## 6. Latihan Postgres Lokal (Docker)

```powershell
docker run -d --name crm-pg -e POSTGRES_DB=crm -e POSTGRES_USER=crm_owner -e POSTGRES_PASSWORD=devpassword -p 127.0.0.1:5432:5432 postgres:17-alpine
docker exec crm-pg pg_isready -U crm_owner -d crm
# buat reader read-only
docker exec crm-pg psql -U crm_owner -d crm -c "CREATE USER crm_reader WITH PASSWORD 'xxx'; GRANT SELECT ON ALL TABLES IN SCHEMA public TO crm_reader;"
# stop/start/rm
docker stop crm-pg; docker start crm-pg; docker rm -f crm-pg
```

Kredensial di atas hanya untuk latihan lokal. DB asli: ambil dari env var / secret manager, jangan hardcode.
`updated_at` harus satu timezone. Container pakai UTC.

## 7. Checklist Sebelum DB Asli

1. Minta ke backend: host, port, nama DB, nama tabel/view, akun **read-only**.
2. `SELECT * FROM tabel LIMIT 0` → cocokkan nama kolom dengan `DB_COLUMN_MAP`.
3. Pastikan ada `updated_at` dan `customer_pk` (atau PK stabil lain).
4. Konfirmasi timezone `updated_at`.
5. Tes: `python -m src.db_export --source postgres://... --table ... --watermark`
