# System Dedupe with Splink

### Probabilistic Record Linkage menggunakan Splink

Sistem **CRM Entity Resolution & Deduplication** untuk mendeteksi, mengevaluasi, dan mengelola duplikasi data pelanggan menggunakan pendekatan *probabilistic record linkage*.

Secara garis besar:

<img width="576" height="274" alt="Image" src="https://github.com/user-attachments/assets/d2e68744-cc55-4b2a-8e71-8785df8c22dd" />

---
## Installation & Setup

1. **Prerequisites**  
   - Python 3.9 or newer  
   - Git (opsional, untuk clone repo)  
   - Docker (opsional, jika ingin jalankan PostgreSQL + API + UI sekaligus)

2. **Clone repository**  
   ```bash
   git clone https://github.com/Boekanadip/dedupe-system-splink.git
   cd dedup-system-splink
3. **Buat virtual environment (disarankan)**  
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

4. **Install dependensi**  
pip install -r requirements.txt
pip install -r requirements-dev.txt   # untuk pengembangan & testing
5. **Jalankan sistem**  
- **Quick start (Windows PowerShell)**  
.\quickstart.ps1
*Script ini akan: membuat venv, menginstall paket, mulai Docker‑Compose (PostgreSQL + API + UI), dan buka UI Streamlit.*
- **Manual step‑by‑step**  
make start          # start Docker Compose (PostgreSQL, API, UI)
make train          # training Splink model
make predict        # batch prediction
make api            # FastAPI di http://localhost:8000
make ui             # Streamlit di http://localhost:8501
make test           # run all tests
6. ** Struktur folder & kegunaan file**  
/ (root repo)
├── .gitignore                # mengabaikan .env, .venv, outputs, models, dsb.
├── .env.example              # template variabel environment (tidak menyimpan password)
├── Dockerfile.api            # Dockerfile untuk service FastAPI
├── Dockerfile.ui             # Dockerfile untuk service Streamlit
├── docker-compose.yml        # menjalankan PostgreSQL, API, UI dalam satu perintah
├── Makefile                  # pintasan: make start, make train, make predict, make api, make ui, make test
├── quickstart.ps1            # script Windows: setup venv + start semua service
├── stop.ps1                  # script untuk menghentikan semua service
├── README.md                 # file ini
│
├── src/
│   ├── __init__.py
│   ├── config.py             # blocking rules, thresholds, & schema validation minimal
│   ├── db.py                 # koneksi PostgreSQL (membaca .env)
│   ├── standardize.py        # mapping kolom & standarisasi (lowercase, phone, email)
│   ├── splink_model.py       # training & inference Splink (EM algorithm)
│   └── validate_upload.py    # validasi kolom minimal: first_name + last_name + (email or phone)
│
├── scripts/
│   ├── batch_predict.py      # jalankan pipeline lengkap dari CSV ke output
│   └── run_pipeline.py       # alternative entry point
│
├── api/
│   └── app.py                # FastAPI endpoint (/predict, /matches, /health)
│
├── ui/
│   └── app.py                # Streamlit dashboard (overview, review queue, master records)
│
├── pages/
│   ├── 1_review.py           # human review pasangan satu‑satu
│   ├── 5_queue.py            # daftar pasangan REVIEW yang pending
│   ├── 6_batch.py            # review batch sebelum digabung ke master
│   └── upload.py             # UI upload CSV
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py           # fixture database untuk test
│   ├── test_schema_validation.py   # test kasus kolom wajib minimal
│   ├── test_system.py
│   └── test_verification.py
│
├── data/
│   ├── raw/                  # CSV mentah yang diupload user
│   ├── processed/            # parquet setelah standardisasi
│   └── labels/               # feedback.csv & gold_labels.csv
│
├── outputs/
│   ├── master_customers.parquet   # master record (satu baris per entity)
│   ├── entity_map.parquet         # mapping record_id → entity_id
│   └── splink_predictions.parquet # semua pasangan dengan skor
│
├── docs/
│   ├── prd.md                  # product requirements (asli)
│   ├── design.md               # desain sistem
│   └── agents.md               # dokumentasi skill AI
│
└── outputs/                  # (file hasil generate, biasanya di‑gitignore)
7. **Point‑point penting (ringkas)**  
- **Schema validation fleksibel**: hanya `first_name` & `last_name` wajib; harus ada **salah satu** dari `email` **atau** `phone`. Kolom lainnya opsional.  
- **Blocking rules**: 14 aturan di `src/config.py` mengurangi kandidat dari O(N²) menjadi ratusan ribu.  
- **Decision threshold**:  
- `>= 0.95` → **AUTO MATCH** ( langsung dimasukkan cluster)  
- `<= 0.01` → **AUTO NON_MATCH** (disimpan untuk audit, **tidak dibuang**)  
- `0.01 – 0.95` → **REVIEW MANUAL** (butuh konfirmasi manusia)
- **Human review**: opsional, hasil disimpan di `data/labels/feedback.csv` & `gold_labels.csv`.  
- **Monitoring & retrain**: metrik match/review rate, alert saat threshold dilanggar, retrain harian/mingguan atau manual via `pages/4_retrain.py`.
8. **Langkah selanjutnya**  
- Buka `http://localhost:8501` untuk melihat UI Streamlit.  
- Coba upload CSV minimal kolom `first_name`, `last_name`, dan `email` / `phone`.  
- Lihat hasil di FastAPI (`http://localhost:8000/docs`) dan dashboard.  
- Jalankan `make test` sebelum distribusi ke environment produksi.
