# CRM Entity Resolution dengan Splink

Aplikasi Streamlit untuk menemukan kemungkinan duplikasi customer melalui **probabilistic record linkage**. Sistem membandingkan beberapa record, memberi skor kemiripan, mengelompokkan record ke `entity_id`, lalu menyediakan antrean pemeriksaan manusia.

> Status: prototype/demo lokal. `MATCH` adalah hasil model, bukan kebenaran yang sudah diverifikasi. `REVIEW` tetap perlu diperiksa manusia.

## Menjalankan aplikasi

### Prasyarat

- Python 3.11+.
- Dependensi pada `requirements.txt`.
- Dataset CSV dengan minimal `first_name`, `last_name`, serta salah satu `email` atau `phone_number`.
- Docker hanya diperlukan untuk fitur PostgreSQL/database. Analisis CSV lokal tidak wajib memakai Docker.

### Instalasi

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Menjalankan Streamlit

```powershell
streamlit run app.py
```

Buka `http://localhost:8501`. Jika port tersebut terpakai:

```powershell
streamlit run app.py --server.port 8502
```

Gunakan `app.py` sebagai entrypoint utama. File `pages/app_streamlit.py` adalah halaman Upload yang didaftarkan melalui `st.navigation`.

## Cara memakai aplikasi

1. Buka **Upload**.
2. Pilih **File CSV**.
3. Upload file customer.
4. Periksa jumlah baris, kolom, delimiter, encoding, nilai kosong, dan duplikat persis.
5. Pilih kolom pembanding: nama, email, telepon, alamat, kota, provinsi, negara, dan tanggal lahir sesuai data yang tersedia.
6. Klik **Analisis batch**.
7. Buka **Ringkasan** untuk melihat hasil umum.
8. Buka **Kesenjangan** untuk melihat record sendirian serta pasangan `REVIEW` yang belum masuk antrean.
9. Masukkan sedikit pasangan, misalnya 20–50, ke **Antrean**.
10. Buka **Pemeriksaan**. Bandingkan dua record lalu pilih gabungkan, bedakan, atau tidak yakin.
11. Buka **Data Master** untuk melihat ringkasan entitas jika artefaknya tersedia.
12. Lewati **Latih Ulang** untuk demo pada dataset besar. Retrain membaca seluruh batch yang terdaftar dan dapat membutuhkan RAM/CPU besar.

## Arti status

- **MATCH / Digabung**: model menilai dua record kemungkinan besar berasal dari entitas yang sama. Record sumber tidak dihapus.
- **REVIEW / Perlu diperiksa**: bukti belum cukup; keputusan manusia diperlukan.
- **NON_MATCH / Berbeda**: model menilai dua record kemungkinan berasal dari entitas berbeda.

`record_id` adalah ID setiap baris. `customer_id` adalah ID dari sistem sumber. `entity_id` adalah ID kelompok hasil resolusi. Ketiganya tidak boleh disamakan.

## Alur di belakang layar

```text
Upload CSV
  -> validasi dan profiling
  -> batch terdaftar
  -> standardisasi kolom menjadi *_std
  -> blocking untuk mencari pasangan kandidat
  -> Splink menghitung match_weight dan match_probability
  -> keputusan MATCH / REVIEW / NON_MATCH
  -> entity_map dan master_customers
  -> review manusia dan evaluasi
```

Data mentah tetap dipertahankan. Standardisasi membuat kolom baru; nilai mentah tidak seharusnya ditimpa.

## Pipeline penuh

`python -m src.run_all` menjalankan tahap berikut:

```text
profiling
standardize
labels_silver
blocking_benchmark
splink_model
labels_review_queue
clustering
master_record
evaluate
version_gold_scores
```

Untuk data besar, jalankan hanya setelah memastikan kapasitas komputer memadai. Gunakan `--sample` untuk smoke test, bukan sebagai hasil produksi:

```powershell
python -m src.run_all --sample
```

Parameter `--full-u-estimation` dapat membutuhkan memori besar. Jangan menjalankannya pada PC demo tanpa mengukur jumlah pasangan terlebih dahulu.

## Pembobotan dan keterbatasan

Model membandingkan kolom terstandardisasi seperti `first_name_std`, `last_name_std`, `email_std`, `phone_std`, lokasi, dan tanggal lahir. `match_probability` adalah bukti model yang perlu dievaluasi; bukan label ground truth.

Distribusi skor harus diperiksa sebelum menetapkan threshold. Dataset tanpa kasus abu-abu dapat menghasilkan hampir semua pasangan berada di ujung skor. Evaluasi yang bermakna membutuhkan label manual, kasus typo, perubahan email/telepon, perubahan alamat, serta tanggal lahir yang tidak sempurna.

Retrain dan perubahan pembobotan tidak dijalankan otomatis setiap kali CSV masuk. Simpan model, evaluasi hasilnya, lalu promosikan versi baru hanya setelah pemeriksaan.

## Struktur utama

```text
app.py                 entrypoint Streamlit dan st.navigation
pages/                 halaman Upload, Ringkasan, Pemeriksaan, Antrean, dan lainnya
src/                   pipeline, standardisasi, Splink, clustering, evaluasi
data/raw/              batch CSV sumber
data/processed/        data terstandardisasi
outputs/               prediksi, entity map, master, laporan
data/labels/           label gold dan antrean review
scripts/                skrip operasional
scripts/dev_checks/    skrip diagnosis/eksperimen lokal
tests/                 pengujian
Dockerfile*             konfigurasi container
docker/                  schema dan migration database
```

## Verifikasi cepat

```powershell
python -m py_compile src/*.py pages/*.py
```

Jalankan test yang relevan sebelum demo:

```powershell
pytest -q
```

## Database/Docker

```powershell
docker compose up -d
```

Gunakan database hanya jika alur koneksi database atau ekspor memang diperlukan. Untuk demo CSV lokal, Docker dapat tetap dimatikan agar RAM tersedia untuk pipeline.

## Catatan keamanan

Jangan commit `.env`, password, token, data customer sensitif, atau artefak besar yang tidak dibutuhkan. Periksa `git status` sebelum commit dan push.
