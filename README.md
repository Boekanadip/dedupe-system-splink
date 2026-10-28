# System Dedupe with Splink

### Probabilistic Record Linkage menggunakan Splink

Sistem **CRM Entity Resolution & Deduplication** untuk mendeteksi, mengevaluasi, dan mengelola duplikasi data pelanggan menggunakan pendekatan *probabilistic record linkage*.

Secara garis besar:

<img width="576" height="274" alt="Image" src="https://github.com/user-attachments/assets/d2e68744-cc55-4b2a-8e71-8785df8c22dd" />

---
## Installation & Setup

1. **Persyaratan**  
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
## 6. Struktur Folder dan Kegunaan File

Berikut struktur direktori repository beserta fungsi setiap file dan folder utama.

```text
/
├── .gitignore
├── .env.example
├── Dockerfile.api
├── Dockerfile.ui
├── docker-compose.yml
├── Makefile
├── quickstart.ps1
├── stop.ps1
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── standardize.py
│   ├── splink_model.py
│   └── validate_upload.py
│
├── scripts/
│   ├── batch_predict.py
│   └── run_pipeline.py
│
├── api/
│   └── app.py
│
├── ui/
│   └── app.py
│
├── pages/
│   ├── 1_review.py
│   ├── 5_queue.py
│   ├── 6_batch.py
│   └── upload.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_schema_validation.py
│   ├── test_system.py
│   └── test_verification.py
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── labels/
│
├── outputs/
│   ├── master_customers.parquet
│   ├── entity_map.parquet
│   └── splink_predictions.parquet
│
└── docs/
    ├── prd.md
    ├── design.md
    └── agents.md
```

### Fungsi File dan Direktori

#### File konfigurasi dan operasional

| File | Fungsi |
|---|---|
| `.gitignore` | Menentukan file dan direktori yang tidak dilacak Git, seperti `.env`, `.venv`, serta artefak hasil generate yang dikecualikan. |
| `.env.example` | Template variabel environment untuk konfigurasi aplikasi tanpa menyertakan kredensial asli. |
| `Dockerfile.api` | Instruksi untuk membangun image Docker service FastAPI. |
| `Dockerfile.ui` | Instruksi untuk membangun image Docker service Streamlit. |
| `docker-compose.yml` | Mengatur service PostgreSQL, API, dan UI melalui Docker Compose. |
| `Makefile` | Menyediakan pintasan perintah untuk menjalankan
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
