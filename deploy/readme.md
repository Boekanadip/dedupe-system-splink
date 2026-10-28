# Deploy ke Cloudflare

Streamlit app (Splink + DuckDB + Postgres). Tidak ada build statis, tidak ada
Cloudflare Pages/Workers. Jalur yang dipakai: **Cloudflare Tunnel** (`cloudflared`)
— app jalan di Docker, Cloudflare yang memberi URL publik. Tidak perlu buka port
router/firewall.

## 1. Jalankan lokal dulu (cek container sehat)

```bash
docker compose up -d --build
docker compose ps
```

Tunggu `crm-app` status `healthy` (±30–60 detik; pertama kali pip install lebih lama).
Buka http://localhost:8501.

Data/tabel Postgres: `postgres://crm_owner:devpassword@127.0.0.1:5432/crm`.
Seed tabel dari host (sekali saja):

```bash
python scripts/seed_postgres.py
```

## 2. Expose ke internet

### Opsi A — Quick tunnel (paling cepat, cocok demo ke mentor)

```bash
docker compose up -d cloudflared
docker compose logs -f cloudflared
```

Cari baris `https://<random>.trycloudflare.com`. Kirim URL itu ke mentor.
Catatan: URL **berubah tiap `cloudflared` restart**, dan tidak ada auth.

### Opsi B — Named tunnel (URL tetap, butuh domain di Cloudflare)

1. Buat tunnel di dashboard Cloudflare → Zero Trust → Networks → Tunnels.
2. Copy token.
3. Set token di `.env` (jangan commit):

   ```env
   CLOUDFLARE_TUNNEL_TOKEN=eyJ...
   ```

4. Tambah Public Hostname di tunnel: `dedup.domain.com` → `http://streamlit:8501`.
5. `docker compose up -d cloudflared`.

## 3. Kalau app di VM/cloud (bukan laptop)

Sama saja. Yang perlu jaringan keluar (port 443) untuk `cloudflared` dan
`docker pull`. Tidak perlu inbound rule.

## 4. Batasan yang harus disampaikan

- **Tanpa auth.** Siapa pun yang punya URL bisa menekan tombol pipeline
  (Upload → Analisis batch, retrain, apply). Untuk demo: bagikan URL, matikan
  `cloudflared` setelah selesai. Untuk produksi: Cloudflare Access (Zero Trust).

  > Peringatan: pipeline ini menulis ke data/models dan bisa menghapus staging.
  > Jangan biarkan URL terbuka publik dalam waktu lama.

- **SQLite/parquet lokal per container.** Data ada di volume `./data`, `./outputs`,
  `./models` (bind mount). Kalau pindah ke Cloudflare Containers/serverless,
  filesystem tidak persisten — butuh object storage (R2) atau Postgres sebagai
  sumber kebenaran. Belum diimplementasikan.

- **Model + artefak ikut image.** Dockerfile tidak menyalin `data/`, `outputs/`,
  `models/` (gitignore). Di compose, folder-folder itu di-mount dari host, jadi
  container membaca artefak yang sudah ada di disk. Build image di mesin yang
  punya data tersebut.

- **DuckDB `INSTALL postgres_scanner`** saat pertama connect ke Postgres — butuh
  internet keluar dari container. Sudah dibuka di compose default (bridge).

## 5. Sebelum go-live / produksi

1. **Buat `.env` dari `.env.example`** dan isi `POSTGRES_PASSWORD` dengan password kuat (jangan gunakan `devpassword` di produksi).
2. `DEDUP_API_KEY` untuk `src/api.py` jika api tersebut dijalankan publik.
3. Aktifkan **Cloudflare Access (Zero Trust)** di tunnel agar tidak siapa pun yang punya URL bisa jalankan pipeline Upload → retrain → apply. Lihat:
   https://developers.cloudflare.com/cloudflare-one/identity/zero-trust

## 6. Troubleshooting

| Gejala | Cek |
|---|---|
| `crm-app` unhealthy | `docker compose logs streamlit` |
| Tunnel tidak dapat URL | `docker compose logs cloudflared` |
| Halaman kosong / error data | pastikan `data/processed/crm_standardized.parquet` dan `models/latest.json` ada di host |
| Upload > 200 MB ditolak | `.streamlit/config.toml` `maxUploadSize = 200` (sudah) |
| Postgres connection refused | `docker compose ps` → `crm-pg` healthy; seed dengan `scripts/seed_postgres.py` |