# CRM Entity Resolution dengan Splink

Sistem menemukan kemungkinan duplikasi customer melalui **probabilistic record linkage** (Splink). Dua antarmuka tersedia: **React dashboard + FastAPI** sebagai UI operasional utama, dan **Streamlit** sebagai alat analisis untuk data scientist.

> Status: prototype/demo lokal. `MATCH` adalah hasil model, bukan kebenaran yang sudah diverifikasi. `REVIEW` tetap perlu diperiksa manusia.

---

## Antarmuka

| | React Dashboard (Nexus) | Streamlit |
|---|---|---|
| Jalankan | `npm run dev` di `nexus-data-intelligence-live/` (port 5174) + FastAPI (port 8000) | `streamlit run app.py` (port 8501) |
| Teknologi | Vite + React + FastAPI + Supabase | Python Streamlit native |
| Navigasi | SPA, sidebar kiri, satu halaman | Multi-halaman via `st.navigation()` |
| Retraining | Ada di menu **Model registry** (retrain, rollback, daftar versi) | Halaman **Retrain** lengkap dengan sweep threshold |
| Batch prediction | Ada (via API, dari menu Processing) | Halaman **Batch** |
| Gaps / unlinked records | Tidak ada | Ada (halaman **Gaps**) |
| Database ingest | Via API (`/api/database/*`, Supabase) | Langsung connect psycopg2 |
| Entity management | Menu **Entity management** (Supabase) | Halaman **Master** |
| Retrain dari UI | `POST /api/model/retrain` | `python -m src.run_all` |
| Rollback model | `POST /api/model/rollback` | Klik di halaman Retrain |

---

## Menjalankan aplikasi

### Prasyarat

- Python 3.11+
- Dependensi pada `requirements.txt`
- Dataset CSV dengan minimal `record_id`, `first_name`, `last_name`
- Docker hanya diperlukan untuk fitur PostgreSQL/database lokal. Analisis CSV/Supabase tidak wajib.
- `.env` di root berisi `DEDUP_API_KEY` (lihat `.env.example`)

### Instalasi

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Menjalankan React Dashboard (Nexus)

```powershell
# Backend FastAPI (port 8000)
.venv\Scripts\python.exe -m uvicorn api.app:app --host 0.0.0.0 --port 8000

# Frontend React (port 5174, proxy /api -> 8000)
cd nexus-data-intelligence-live
npm install
npm run dev
```

Buka `http://localhost:5174`.

**Catatan:**
- Vite proxy meneruskan semua request `/api/*` dan `/health` ke `http://localhost:8000`.
- Header `x-api-key` otomatis ditambahkan oleh Vite dari `DEDUP_API_KEY` di `.env`.
- Jika Supabase tidak dikonfigurasi, endpoint Supabase balas 503 — fitur lokal tetap jalan.

### Menjalankan Streamlit

```powershell
.venv\Scripts\Activate.ps1
streamlit run app.py
```

Buka `http://localhost:8501`. Gunakan `app.py` sebagai entrypoint.

---

## Cara memakai React Dashboard

1. Buka **Data sources** → **File sources** → upload CSV/Parquet, atau **Database connections** → ingesta tabel Supabase.
2. File wajib punya kolom: `record_id`, `first_name`, `last_name`. Kolom tambahan (`email`, `phone`, `dob`, `city`, `state`, `country`, `address`) menaikkan akurasi.
3. Buka **Processing** → pilih **Backend dataset** dari dropdown → klik **Run pipeline**.
4. Hasil: dashboard menampilkan `stats`, `pairs`, `review queue`, `run history` secara otomatis.
5. Buka **Model registry** → klik **Retrain** untuk latih ulang, atau pilih versi lama dan klik **Roll back**.
6. Download hasil: klik ikon **Download** di Overview atau Processing.
7. Simpan ke DB: `POST /api/save-outputs` (PostgreSQL lokal) atau via Supabase.

> Hasil run baru **menimpa** hasil lama. Jika ingin simpan hasil lama, salin `outputs/splink_predictions.parquet` sebelum run baru.

---

## Cara memakai Streamlit

1. Buka **Upload**. Pilih file CSV.
2. Upload, periksa jumlah baris/kolom/duplikat.
3. Pilih kolom pembanding. Klik **Analisis batch**.
4. Buka **Ringkasan**, **Kesenjangan**, **Antrean**, **Pemeriksaan**, **Data Master** sesuai kebutuhan.
5. **Retrain**: klik **Retrain** di halaman model. Jalankan `python -m src.run_all` sebagai proses background. Tunggu selesai lalu refresh.

---

## Retraining Model (React)

Model versi disimpan di `models/<version>/` dengan struktur:

```text
models/
  latest.json          # pointer versi aktif
  vYYYYMMDD_HHMMSS/
    model.json         # aturan perbandingan + probabilitas m/u
    metadata.json      # input, scope, runtime, blocking rules
    thresholds.json    # match_threshold, review_threshold
    evaluation.json    # distribusi keputusan dari run
```

Endpoint:

| Method | Path | Keterangan |
|---|---|---|
| GET | `/api/model/info` | Versi aktif + threshold |
| GET | `/api/model/versions` | Daftar semua versi tersimpan |
| POST | `/api/model/retrain` | Jalankan retrain background (`run_all`) |
| POST | `/api/model/rollback` | Kembalikan `latest.json` ke versi target |

Retrain dijalankan sebagai proses `subprocess` dengan log di `outputs/retrain.log`.

---

## Arti status

- **MATCH / Digabung**: model menilai dua record kemungkinan besar berasal dari entitas yang sama.
- **REVIEW / Perlu diperiksa**: bukti belum cukup; keputusan manusia diperlukan.
- **NON_MATCH / Berbeda**: model menilai dua record kemungkinan berasal dari entitas berbeda.

`record_id` adalah ID setiap baris. `customer_id` adalah ID dari sistem sumber. `entity_id` adalah ID kelompok hasil resolusi.

---

## Alur di belakang layar

```text
Upload / Ingest
  -> validasi dan profiling
  -> standardisasi kolom menjadi *_std
  -> blocking untuk mencari pasangan kandidat
  -> Splink menghitung match_weight dan match_probability
  -> keputusan MATCH / REVIEW / NON_MATCH
  -> entity_map dan master_customers
  -> review manusia dan evaluasi
```

Data mentah tetap dipertahankan. Standardisasi membuat kolom baru; nilai mentah tidak dihapus.

## Pipeline penuh

`python -m src.run_all` menjalankan:

```text
profiling -> standardize -> labels_silver -> blocking_benchmark
-> splink_model -> labels_review_queue -> clustering
-> master_record -> evaluate -> version_gold_scores
```

Untuk data besar gunakan `--sample` sebagai smoke test; `--full` untuk produksi.

## Pembobotan dan keterbatasan

Model membandingkan kolom terstandardisasi seperti `first_name_std`, `last_name_std`, `email_std`, `phone_std`. `match_probability` adalah skor model, bukan label ground truth.

Evaluasi bermakna membutuhkan label manual, kasus typo, perubahan email/telepon/alamat.

## Struktur utama

```text
api/                    FastAPI server (port 8000)
  app.py                endpoint: /api/*, /health, /api/model/*
  db.py                 koneksi PostgreSQL lokal
nexus-data-intelligence-live/
  src/App.jsx           UI React utama
  src/services/dedupApi.js  bridge API
pages/                  halaman Streamlit
src/                    pipeline, standardisasi, Splink, model_lifecycle
data/                   direktori kerja lokal (gitignored)
outputs/                direktori kerja lokal (gitignored)
models/                 versi model hasil training (gitignored)
docs/                   dokumentasi teknis
tests/                  pengujian
```

Data, model, output, log sengaja tidak masuk git. Siapkan artefak lokal sebelum menjalankan pipeline penuh.

## Verifikasi cepat

```powershell
python -m py_compile src/*.py api/app.py
pytest -q
```

## Database / Docker

```powershell
docker compose up -d
```

Untuk demo lokal tanpa PostgreSQL, cukup siapkan Supabase atau file lokal.

## Catatan keamanan

Jangan commit `.env`, password, token, atau data customer sensitif. Periksa `git status` sebelum commit dan push.
