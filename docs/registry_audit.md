# Registry Audit Report

**Tanggal:** 2026-11-17  
**Tujuan:** Mengaudit konsistensi batch registry vs parquet vs artefak entity/master.  
**Status:** Selesai (read-only, tidak mengubah data).

---

## Temuan

### 1. Registry internal

- **Batches terdaftar:** 17
- **Total rows terdaftar:** 108.617
- **next_start_index:** 108.618
- **Duplicate sha256:** tidak ditemukan
- **Batch terakhir:** `synthetic_test.csv` (batch_id 17, 190 baris), tercatat pada `start_index=132727`, `record_id_range=rec_132728..rec_132917`.

### 2. Registry vs `crm_standardized.parquet`

| Sumber | Row count | Range `record_id` |
|---|---:|---|
| Registry total | 108.617 | — |
| `crm_standardized.parquet` | 108.617 | `rec_000001` – `rec_108617` (108.617 unik) |

Parquet kini memuat seluruh baris yang setara total registry, tetapi **penomoran `record_id` tidak mengikuti `record_id_range` batch 17**. Batch 17 tercatat di `rec_132728..rec_132917`, sedangkan parquet berakhir di `rec_108617`. Artinya rentang `record_id` batch 17 di registry tidak konsisten dengan isi parquet.

### 3. Baris hasil DB/sintetik di parquet

- 6.572 baris memiliki `customer_pk` non-null (`customer_pk` adalah penanda baris yang berasal dari jalur DB).
- Jumlah ini setara dengan batch 12–16: 2.000 + 3 + 1.566 + 2.003 + 1.000 = 6.572.
- Baris tersebut **belum dibersihkan** dari parquet kerja.

### 4. Artefak entity/master

| Artefak | Records | Entities | Scope | Catatan |
|---|---:|---:|---|---|
| `outputs/entity_map.parquet` | 108.617 | 108.541 | `partial` | 78 match edge, 102.702 record belum di-score |
| `outputs/master_customers.parquet` | 108.617 | 108.541 | `partial` | Diturunkan dari entity_map `partial` |

Scope `partial` berarti entity map belum mencakup seluruh pasangan kandidat. Master record dari artefak ini juga parsial; jangan dibaca sebagai hasil full pipeline.

### 5. Artefak pendukung lain

- `outputs/splink_predictions.parquet`: 200 pasangan (bukan prediksi penuh).
- `outputs/evaluation_report.json`: scope `sample`, model `v20261116_122048`, 5.289 pasangan kandidat.
- `data/labels/gold_labels.csv`: 3.890 pasangan (1.372 `match`, 2.518 `no_match`).
- `data/labels/review_queue.csv`: 201 pasangan, semuanya `pending`.

### 6. Status DB PostgreSQL

Angka tabel PostgreSQL **tidak diverifikasi pada audit ini** karena database tidak di-query. Klaim lama tentang `processed_customers`, `entity_map`, dan `master_customer_current` tidak boleh dipakai tanpa `SELECT COUNT(*)` ulang.

---

## Bukti

- Registry JSON: `data/processed/batch_registry.json`.
- Parquet: `data/processed/crm_standardized.parquet` + `.meta.json`.
- Entity/master: `outputs/entity_map.parquet` dan `outputs/master_customers.parquet` + `.meta.json`.
- Gold/review: `data/labels/gold_labels.csv`, `data/labels/review_queue.csv`.

---

## Rekomendasi

### 1. Selaraskan `record_id` batch 17
Putuskan apakah batch 17 tetap di `rec_132728..rec_132917` (dan parquet harus menyusul) atau renumbering ke `rec_108428..rec_108617`. Jangan biarkan registry dan parquet berbeda.

### 2. Bersihkan baris `customer_pk` bila ingin corpus CSV murni
6.572 baris berasal dari jalur DB/sintetik. Bila tujuan audit adalah data CSV, buang baris `customer_pk` non-null ke artefak terpisah, lalu jalankan ulang `python -m src.clustering` dan `python -m src.master_record`.

### 3. Regenerasi artefak entity/master dari scope yang disepakati
Scope `partial` saat ini membuat master record tidak lengkap. Jalankan pipeline penuh sebelum mengklaim jumlah entity final.

### 4. Audit DB terpisah
Jalankan `SELECT COUNT(*)` pada tabel PostgreSQL yang relevan sebelum mencatat status DB di dokumen.

### 5. Jangan daftar ulang file batch lama
File di `data/raw/` yang tidak tercatat registry tidak perlu didaftarkan hanya untuk menyamakan angka. Pastikan dulu asal-usul dan dampaknya ke `next_start_index`.
