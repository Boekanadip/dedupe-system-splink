# Kondisi Aktual Repository

Diperbarui: 2026-11-17

Dokumen ini menjadi catatan kondisi repository saat ini. Angka hasil pipeline lama tetap bersifat historis dan tidak boleh dibaca sebagai metrik model aktif.

## Kode aktif

- UI utama: `app.py` + `pages/`.
- Pipeline: `src/`.
- Engine linkage: Splink dengan eksekusi Python/DuckDB.
- Blocking default: 12 aturan di `DEFAULT_BENCHMARK_RULES` (`src/config.py`), dimuat lewat `load_benchmark_rules()`.
- Threshold default: `MATCH_THRESHOLD=0.84`, `REVIEW_THRESHOLD=0.35` (`src/config.py`).
- Review queue utama: PostgreSQL `splink_data.review_queue_records`.
- Persistensi review: `src/review_db.py`, dengan migration `docker/migrations/002_review_queue_records.sql`.
- Persistensi output/job: `src/persist.py` dan migration `docker/migrations/003_create_export_targets.sql` serta `004_pipeline_persistence.sql`.
- Jalur database: CLI melalui `src/db_source.py`, `src/db_export.py`, `src/job_run.py`, dan `src/db_refresh.py`.

## Snapshot artefak lokal (2026-11-17)

Angka berikut berasal dari artefak lokal, bukan isi clone GitHub:

- Registry: 17 batch, 108.617 baris, `next_start_index=108618`.
- `data/processed/crm_standardized.parquet`: 108.617 baris; 6.572 baris memiliki `customer_pk` non-null.
- `outputs/entity_map.parquet`: 108.617 record, 108.541 entity, 78 match edge, scope `partial`, 102.702 record belum di-score.
- `outputs/splink_predictions.parquet`: 200 pasangan pada artefak saat ini; bukan hasil prediksi penuh.
- `outputs/master_customers.parquet`: 108.541 entity, scope `partial`.
- `data/labels/gold_labels.csv`: 3.890 pasangan (1.372 `match`, 2.518 `no_match`).
- `data/labels/review_queue.csv`: 201 pasangan, semuanya `pending`.
- Model terakhir yang dipakai artefak: `v20261116_122048` (scope `sample`, 10.000 baris input, 5.289 pasangan). Pointer `models/latest.json` masih menunjuk `v20261027_074552` karena run sample tidak memperbarui pointer.

## Artefak lokal

Data customer, hasil pipeline, model, snapshot label, log, serta eksperimen lokal tidak menjadi bagian repository GitHub. Artefak tersebut dibuat atau dipasang di lingkungan lokal sesuai kebutuhan.

Direktori kerja lokal yang bukan source of truth Git:

- `data/raw/`
- `data/processed/`
- `data/synthetic/`
- `outputs/`
- `models/`
- `scripts/dev_checks/`

Clone bersih membutuhkan data/model yang sesuai sebelum menjalankan pipeline penuh. Jangan menganggap clone bersih berisi hasil prediksi atau model terlatih.

## Batasan yang terverifikasi

- `MATCH` adalah keputusan model, bukan ground truth.
- `REVIEW` membutuhkan keputusan manusia.
- `record_id`, `customer_id`, dan `entity_id` berbeda.
- Raw value harus dipertahankan; standardisasi memakai kolom terpisah.
- Retraining tidak otomatis terjadi setiap kali CSV baru masuk.
- Threshold, blocking coverage, akurasi, runtime, dan skala produksi belum boleh diklaim tanpa eksperimen yang dapat direproduksi.
- Tidak ada autentikasi produksi, scheduler produksi, atau deployment produksi yang diverifikasi.

## Keamanan

- Secret harus berasal dari environment variable atau secret manager.
- Password contoh Docker hanya untuk lokal; jangan gunakan di produksi.
- Jangan commit data customer, token, password, atau output yang memuat data sensitif.
