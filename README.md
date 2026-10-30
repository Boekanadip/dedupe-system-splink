# System Dedupe with Splink

### Probabilistic Record Linkage menggunakan Splink

Sistem **CRM Entity Resolution & Deduplication** untuk mendeteksi, mengevaluasi, dan mengelola duplikasi data pelanggan menggunakan pendekatan *probabilistic record linkage*.

Secara garis besar:

<img width="576" height="274" alt="Image" src="https://github.com/user-attachments/assets/d2e68744-cc55-4b2a-8e71-8785df8c22dd" />

## Instalasi

1. Clone repository
2. Install dependensi: `pip install -r requirements.txt`
3. Jalankan Docker: `docker-compose up -d`
4. Jalankan aplikasi: `streamlit run pages/app_streamlit.py`

## Struktur Folder

```
├── .opencode/        <-- Folder implementasi AI agent (tidak dipush ke GitHub)
├── .gitignore        <-- File ignore Git
├── .env.example      <-- Contoh variabel environment
├── config/           <-- Konfigurasi Splink dan blocking rules
├── data/             <-- Data mentah dan hasil processing
├── outputs/          <-- File output (parquet, results)
├── scripts/          <-- Script batch dan otomasi
├── src/              <-- Source code utama
│   └── config.py     <-- Column mapping dan konfigurasi
├── tests/            <-- Test suite
├── pages/            <-- Aplikasi Streamlit
├── api/              <-- FastAPI endpoints
├── ui/               <-- Antarmuka pengguna
├── docker/           <-- Konfigurasi Docker
├── .env              <-- Environment variables (lokal)
├── Makefile          <-- Perintah build dan testing
├── requirements.txt  <-- Dependensi Python
└── README.md         <-- Dokumentasi ini
```

## Kegunaan File Utama

- `src/config.py` - Konfigurasi column mapping Splink dan 14 blocking rules
- `scripts/batch_predict.py` - Script prediksi batch harian
- `pages/1_review.py` - Review pasangan ambiguitas secara manual
- `pages/5_queue.py` - Antrean pasangan REVIEW yang pending
- `pages/6_batch.py` - Batch review sebelum digabung ke master
- `api/app.py` - REST API endpoint untuk aplikasi eksternal
- `ui/app.py` - Dashboard Streamlit interaktif
- `docker-compose.yml` - Layanan PostgreSQL, Streamlit, dan lainnya
- `Makefile` - Target build, test, dan pipeline otomatisasi
- `.env.example` - Contoh variabel environment untuk development