# Kondisi Aktual Repository

Diperbarui: 2026-11-11

Dokumen ini menjadi catatan kondisi repository saat ini. Angka hasil pipeline lama tetap bersifat historis dan tidak boleh dibaca sebagai metrik model aktif.

## Kode aktif

- UI utama: `app.py` + `pages/`.
- Pipeline: `src/`.
- Engine linkage: Splink dengan eksekusi Python/DuckDB.
- Review queue utama: PostgreSQL `splink_data.review_queue_records`.
- Persistensi review: `src/review_db.py`, dengan migration `docker/migrations/002_review_queue_records.sql`.
- Persistensi output/job: `src/persist.py` dan migration `docker/migrations/003_create_export_targets.sql` serta `004_pipeline_persistence.sql`.
- Jalur database: CLI melalui `src/db_source.py`, `src/db_export.py`, `src/job_run.py`, dan `src/db_refresh.py`.

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
