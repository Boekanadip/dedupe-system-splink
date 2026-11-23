# Nexus Data Intelligence — Live Integration Build

## Apa yang berbeda dengan folder `nexus-data-intelligence - Copy`

- Semua UI/UX tetap sama (App.jsx, components inline, styles.css).
- Ditambahkan `src/services/dedupApi.js`: bridge tipis dari konsep platform ke endpoint FastAPI (`/health`, `/api/stats`, `/api/pairs`, `/api/run-dedup`, dll).
- Vite di-dev mode dialihkan ke port **5174** dan semua request `/api/*` serta `/health` diproyeksikan ke `http://localhost:8000` lewat proxy (bukan CORS).
- `.env` berisi `VITE_API_BASE_URL=` kosong → pakai proxy.
- `App.jsx` baru membaca state live (`liveState: loading | live | offline`) dan menyalurkan data dashboard + review queue dari API real saat tersedia. Halaman lain (sources, datasets, database, settings) tetap memakai data sample.

## Menjalankan

### 1. Backend Splink FastAPI harus berjalan dulu
```powershell
cd C:\Users\User\Downloads\dedup-system-splink
python -m uvicorn src.api:app --host 0.0.0.0 --port 8000
# atau gunakan api/app.py jika ingin versi terbaru
```
Tambahkan di `.env` backend agar CORS menerima dev server Vite jika proxy dilewati:
```
CORS_ALLOWED_ORIGINS=http://localhost:5174
```

### 2. Pastikan ada predictions
Endpoint `/api/stats` hanya bekerja kalau `outputs/splink_predictions.parquet` sudah ada. Jalankan sekali:
```powershell
cd C:\Users\User\Downloads\dedup-system-splink
python -m src.run_all --sample
```

### 3. Frontend
```powershell
cd C:\Users\User\Downloads\dedup-system-splink\nexus-data-intelligence-live
npm install   # hanya jika node_modules belum disalin
npm run dev
```
Buka <http://localhost:5174>. Badge "LIVE / OFFLINE / CONNECTING" di banner dashboard menunjukkan status koneksi.

## Batasan integrasi ini

- Review pair detail (email/city/phone) tidak ditampilkan oleh endpoint `/api/pair/{id1}/{id2}` backend. Nilai atribut sumber muncul sebagai "—"; tombol Confirm match / Not a match masih menyimpan keputusan secara lokal sampai endpoint review decision dibuat di backend.
- Endpoint model registry (`/api/models`) belum ada. Halaman Model menampilkan model Splink secara statis dan badge akan menunjukkan "Adapter terhubung" berdasarkan status live, bukan metadata model.
- History run hanya menampilkan history demo sampai endpoint `/api/jobs` tersedia di backend.

## Struktur file baru

```
nexus-data-intelligence-live/
├── .env                  # VITE_API_BASE_URL kosong = pakai proxy
├── .env.example
├── package.json          # dependency sama, version bumped jadi 1.2.0
├── vite.config.js        # proxy target ke localhost:8000
└── src/
    ├── services/
    │   ├── dedupApi.js   # client + mapper keReviewRow()
    │   └── platformApi.js
    ├── App.jsx           # ditambahkan loadLive/useEffect + live badge
    ├── main.jsx
    └── styles.css
```

Original folder `nexus-data-intelligence - Copy` **tidak diubah**. Folder `nexus-data-intelligence-live` bisa digunakan sekaligus untuk pengembangan lanjutan tanpa mengganggu repo asli.
