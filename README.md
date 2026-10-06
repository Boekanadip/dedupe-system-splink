# System Dedupe with Splink

### Probabilistic Record Linkage menggunakan Splink, DuckDB, dan Streamlit

Sistem **CRM Entity Resolution & Deduplication** untuk mendeteksi, mengevaluasi, dan mengelola duplikasi data pelanggan menggunakan pendekatan *probabilistic record linkage*.

Pipeline utama:

<img width="2265" height="2151" alt="Image" src="https://github.com/user-attachments/assets/692a6d6a-58e0-4b1a-92e5-b2928cf18eb6" />

Dibangun menggunakan **Python, Splink, DuckDB, Pandas, PyArrow, dan Streamlit**.

> Dataset `crm_50000_customers_dirty_v3.csv` digunakan sebagai dataset pengembangan dan evaluasi awal.
---

# 1. Quick Start — Menjalankan Demo

Bagian ini adalah jalur utama untuk orang yang baru pertama kali menjalankan project di laptop lain.

## 1.1 Persyaratan

Pastikan sudah tersedia:

* Python 3.10 atau lebih baru
* Git
* Windows, Linux, atau macOS
* Dataset dan/atau artifact yang dibutuhkan project
* Koneksi internet saat proses clone dan instalasi dependency

Project dikembangkan menggunakan Python 3.14. DuckDB berjalan secara lokal di dalam aplikasi.

---

## 1.2 Clone repository

```powershell
git clone https://github.com/Boekanadip/dedupe-system-splink.git
cd dedupe-system-splink
```

Pastikan posisi terminal sudah berada di folder:

```text
dedupe-system-splink/
```

Cek isi repository:

```powershell
dir
```

---

## 1.3 Buat virtual environment

```powershell
python -m venv .venv
```

Aktifkan:

```powershell
.venv\Scripts\Activate.ps1
```

Jika PowerShell menolak menjalankan script, gunakan:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Kemudian ulangi:

```powershell
.venv\Scripts\Activate.ps1
```

Jika berhasil, biasanya nama environment akan muncul di awal terminal:

```text
(.venv) PS C:\...\dedupe-system-splink>
```

---

## 1.4 Install dependency

Setelah virtual environment aktif:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Dependency utama project meliputi:

* `splink==4.0.17`
* `duckdb`
* `pandas`
* `pyarrow`
* `streamlit`

Versi lengkap mengikuti `requirements.txt`. Itu sumber yang benar — kalau ada
library yang dipakai kode tapi tidak ada di sana, `requirements.txt` yang ketinggalan,
bukan kodenya.

Dua hal yang perlu diketahui:

* `duckdb` tidak ditulis eksplisit di `requirements.txt`, tapi dipakai langsung oleh
  beberapa modul dan juga dibawa oleh `splink`. Biasanya terpasang otomatis.
* `pages/4_retrain.py` mengimpor `psutil`, dan `psutil` **tidak** ada di
  `requirements.txt`. Kalau halaman Latih Ulang membuka `ModuleNotFoundError: psutil`,
  jalankan `pip install psutil`. Ini keterbatasan repository, bukan kesalahan install Anda.

---

# 2. Verifikasi Instalasi

Sebelum menjalankan pipeline atau Streamlit, jalankan smoke test:

```powershell
python tests/test_smoke.py
```

Smoke test digunakan untuk memeriksa invariant utama project.

Output yang diharapkan pada versi repository saat ini:

```text
23 / 23
```

Jika smoke test gagal, jangan langsung menjalankan proses training. Periksa error yang ditampilkan terlebih dahulu.

> Smoke test memeriksa kondisi internal pipeline. Smoke test bukan pengganti pengecekan apakah aplikasi Streamlit dapat dibuka.

---

# 3. Menyiapkan Dataset

Dataset pengembangan utama:

```text
crm_50000_customers_dirty_v3.csv
```

Dataset berasal dari Kaggle Customer 360 dan digunakan untuk pengembangan/evaluasi.

**File ini TIDAK ikut di repository.** Pola `data/raw/*` ada di `.gitignore`, jadi setelah
`git clone` folder `data/raw/` hanya berisi file `.gitkeep`. Pipeline `src.run_all`
akan gagal di langkah `profiling` kalau file CSV tidak ditempatkan manual di:

```text
data/raw/crm_50000_customers_dirty_v3.csv
```

(Path diambil dari `src/config.py:7` — `RAW_DATA_PATH`.)

Jika Anda sudah punya dataset CRM lain, letakkan di path itu (atau sesuaikan
`src/config.py` jika memang perlu). Jangan mengubah config hanya agar file terbaca
tanpa memahami pemetaan kolomnya.

Repository menggunakan struktur:

```text
data/
├── raw/       ← CSV mentah (gitignored, letakkan dataset di sini)
├── processed/ ← hasil standardisasi (gitignored, dibuat pipeline)
└── labels/    ← review/gold/feedback (gitignored, dibuat pipeline)
```

Validasi file (kolom wajib, delimiter, encoding):

```powershell
python -m src.validate_upload data/raw/crm_50000_customers_dirty_v3.csv
```

---

# 4. Menjalankan Aplikasi Demo

Jika tujuan utama hanya **melihat dan mendemokan aplikasi**, jalankan Streamlit:

```powershell
python -m streamlit run app.py
```

Jika perintah `streamlit run app.py` tidak dikenali, gunakan bentuk di atas.

Setelah berhasil, Streamlit akan menampilkan alamat lokal aplikasi, biasanya:

```text
http://localhost:8501
```

Buka alamat tersebut di browser.

---

# 5. Jalur Demo yang Disarankan

Untuk demo gunakan urutan:

```text
1. Clone repository
        ↓
2. Buat virtual environment
        ↓
3. Install requirements
        ↓
4. Jalankan smoke test
        ↓
5. Pastikan dataset/artifact tersedia
        ↓
6. Jalankan Streamlit
        ↓
7. Upload / proses data
        ↓
8. Review hasil
```

Jangan menjalankan training ulang hanya karena ingin membuka aplikasi.

---

# 6. Pipeline Development

Pipeline lengkap dapat dijalankan dengan:

```powershell
python -m src.run_all
```

Perintah tersebut digunakan ketika memang ingin menjalankan pipeline lengkap dan melakukan training model baru sesuai konfigurasi project.

Untuk menggunakan model yang sudah tersimpan:

```powershell
python -m src.run_all --reuse-model latest
```

### Perbedaan kedua perintah

| Perintah                                     | Kegunaan                                                                 |
| -------------------------------------------- | ------------------------------------------------------------------------ |
| `python -m src.run_all`                      | Menjalankan pipeline dengan training/model processing sesuai konfigurasi |
| `python -m src.run_all --reuse-model latest` | Menggunakan model tersimpan yang ditunjuk `latest`                       |
| `python tests/test_smoke.py`                 | Memeriksa invariant pipeline                                             |
| `python -m streamlit run app.py`             | Menjalankan aplikasi web                                                 |

Training ulang **bukan proses otomatis setiap kali data baru masuk**.

---

# 7. Arsitektur Sistem

```text
                    DATA INPUT
                        │
                        ▼
                Schema Validation
                        │
                        ▼
               Record ID Generation
                        │
                        ▼
                Data Standardization
                        │
                        ▼
              Blocking / Candidate
                  Generation
                        │
                        ▼
             Splink Probabilistic
                Record Linkage
                        │
                        ▼
              Decision Classification
                 /       |       \
                /        |        \
            MATCH      REVIEW    NON_MATCH
               │          │
               │     Human Review
               │          │
               └──────────┘
                        │
                        ▼
                   Clustering
                        │
                        ▼
                    Entity ID
                        │
                        ▼
                  Master Record
                        │
                        ▼
              Evaluation & Feedback
```

## Komponen utama

| Komponen                | Fungsi                                                                 |
| ----------------------- | ---------------------------------------------------------------------- |
| Data validation         | Memeriksa skema, kolom wajib, delimiter, dan encoding                  |
| Record ID generation    | Membuat identifier internal untuk setiap record                        |
| Standardization         | Menormalisasi data tanpa menimpa nilai asli                            |
| Blocking                | Mengurangi jumlah pasangan yang perlu dibandingkan                     |
| Splink                  | Menghitung probabilistic linkage menggunakan pendekatan Fellegi-Sunter |
| Decision classification | Menghasilkan `MATCH`, `REVIEW`, atau `NON_MATCH`                       |
| Human review            | Memvalidasi pasangan yang membutuhkan pemeriksaan                      |
| Clustering              | Mengelompokkan record yang memiliki hubungan MATCH                     |
| Master record           | Membentuk representasi utama setiap entity                             |
| Evaluation & feedback   | Mengevaluasi hasil dan menyimpan feedback manusia                      |

---

# 8. Identifier

Tiga identifier utama tidak boleh disamakan.

| Identifier    | Fungsi                                                |
| ------------- | ----------------------------------------------------- |
| `record_id`   | Identifier internal untuk setiap record yang diproses |
| `customer_id` | Identifier yang berasal dari source system            |
| `entity_id`   | Identifier hasil entity resolution                    |

`customer_id` tidak otomatis dianggap sebagai kebenaran identitas pelanggan.

`device_id` digunakan sebagai referensi/verifikasi pada evaluasi tertentu dan bukan merupakan blocking key maupun field pembanding utama.

---

# 9. Struktur Repository

```text
.
├── app.py
├── pages/
│   ├── 1_review.py
│   ├── 2_master.py
│   ├── 3_dashboard.py
│   ├── 4_retrain.py
│   ├── 5_queue.py
│   ├── 6_batch.py
│   ├── 7_gaps.py
│   ├── 8_explain.py
│   └── 9_history.py
│
├── src/
│   ├── config.py
│   ├── validate_upload.py
│   ├── profiling.py
│   ├── standardize.py
│   ├── registry.py
│   ├── blocking_benchmark.py
│   ├── splink_model.py
│   ├── clustering.py
│   ├── master_record.py
│   ├── labels.py
│   ├── feedback.py
│   ├── apply_gold.py
│   ├── close_gold_loop.py
│   ├── entity_correction.py
│   ├── evaluate.py
│   ├── eval_truth.py
│   ├── threshold_eval.py
│   ├── scenario_eval.py
│   ├── export_linkage.py
│   ├── review_sample.py
│   ├── stress_test.py
│   ├── batch_eval.py
│   ├── incremental.py
│   ├── model_lifecycle.py
│   ├── ui.py
│   └── run_all.py
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── labels/
│
├── models/
├── outputs/
├── tests/
│   └── test_smoke.py
│
├── notebooks/
├── .streamlit/
│   └── config.toml
├── requirements.txt
├── PANDUAN.md
└── README.md
```

---

# 10. Pengelolaan Data dan Artifact

## `data/raw/`

Dataset mentah yang digunakan pipeline.

## `data/processed/`

Hasil standardisasi dan data intermediate, termasuk format Parquet.

## `data/labels/`

Data yang berhubungan dengan review dan evaluasi, seperti:

* silver labels
* review queue
* gold labels
* feedback

## `models/`

**Versi model TERSEDIAP di git.** Setiap clone langsung membawa model yang pernah
dilatih. Ini adalah hasil dari beberapa `run_all` sebelumnya yang dilacak:

```text
models/
├── latest.json
├── v20260930_142409/
│   ├── model.json
│   ├── metadata.json
│   ├── thresholds.json
│   └── evaluation.json
├── v20261001_092908/
│   ├── model.json
│   ├── metadata.json
│   ├── thresholds.json
│   └── evaluation.json
├── v20261001_141528/
│   ├── model.json
│   ├── metadata.json
│   ├── thresholds.json
│   └── evaluation.json
├── v20261005_142821/
│   ├── model.json
│   ├── metadata.json
│   ├── thresholds.json
│   └── evaluation.json
└── v20261005_145258/
    ├── model.json
    ├── metadata.json
    ├── thresholds.json
    └── evaluation.json
```

File `latest.json` selalu menunjuk ke versi terbaru. Halaman Streamlit dan
`pages/6_batch.py` membacanya secara default. Jika Anda mengubah atau menghapus
versi, pastikan model aktif diatur kembali atau jalankan:

```powershell
python -m src.run_all --reuse-model latest
```

Contoh struktur minimal (versi baru dibuat saat pipeline dijalankan):

```text
models/
├── latest.json
└── v<tanggal_waktu>/...
```

## `outputs/` dan `data/`

Folder ini **hanya berisi `.gitkeep`** setelah clone. Artifact-artifact penting
(clustering, entity map, prediksi, dll.) dibuat oleh pipeline saat dijalankan.

Lihat alurnya:

* Setelah `run_all` atau `app.py` diproses, `outputs/` akan diisi berisi:
  `splink_predictions.parquet`, `entity_map.parquet`, `master_customers.parquet`,
  `run_summary.json`, `thresholds_override.json` (jika ada).
* `data/processed/` diisi dengan `crm_standardized.parquet`.
* `data/labels/` diisi dengan `review_queue.csv`, `gold_labels.csv`, `feedback.csv`.

Jika halaman Streamlit menampilkan pesan **"Belum ada data"** atau
**"artifact not found"**, berarti Anda baru clone dan belum menjalankan
pipeline. Jalankan langkah validasi/setup lalu jalankan Streamlit.

**Catatan:** Data pelanggan, file CSV besar, hasil intermediate, dan artifact
hanya diperlukan mesin tertentu tidak boleh dimasukkan ke repository tanpa pemeriksaan
terlebih dahulu. File penting dipisahkan sesuai aturan `.gitignore`.

---

# 11. Model Lifecycle & Feedback Loop

Model disimpan berdasarkan versi dengan pola:

```text
models/
├── v<version>/
│   ├── model.json
│   ├── metadata.json
│   ├── thresholds.json
│   └── evaluation.json
└── latest.json
```

| File              | Fungsi                                         |
| ----------------- | ---------------------------------------------- |
| `model.json`      | Parameter model Splink, termasuk m/u           |
| `metadata.json`   | Informasi training, seed, library, dan runtime |
| `thresholds.json` | Kebijakan threshold                            |
| `evaluation.json` | Ringkasan evaluasi model                       |
| `latest.json`     | Menunjukkan model aktif                        |

Setelah clustering atau hasil model baru, yang terpenting: **tidak ada yang langsung di-"terima" mentah.**

Alurnya berjalan dua arah, tidak lurus:

```text
Upload (app.py)
  ├─ run_all --full  (belum ada model)  → buat model + artifact
  └─ incremental --stage (sudah ada model) → buat proposal staging

Hasil (predictions + entity_map + master) muncul.
↓
pages/6_batch.py  → review batch baru SEBELUM digabung (human gate)
pages/5_queue.py  → daftar pasangan REVIEW yang perlu diperiksa
pages/1_review.py  → putuskan match/no_match per pasangan
  ↓
"Tersimpan ke daftar utama" → src.labels --promote → data/labels/gold_labels.csv

src.close_gold_loop --all  (bisa juga manual 1-2 langkah)
  → src.feedback  (append-only)
  → src.apply_gold --apply --recluster  (ubah decision, recluster, rebuild master)
  → src.evaluate / scenario_eval / threshold_eval

Hasil revisi ini bisa langsung dipakai. Untuk mengubah parameter model,
keputusan retrain tetap **eksplisit** di pages/4_retrain.py.
```

**Kuncinya:**

* `feedback.csv` & `gold_labels.csv` **tidak** membuat model retrain sendiri.
* Mengubah threshold bisa tanpa retrain (lihat `outputs/thresholds_override.json`).
* Retrain cuma terjadi kalau ditekan **"Retrain sekarang"** di halaman Latih Ulang.
* Setelah "Apply" batch atau setelah `close_gold_loop`, kembali ke review/eksplorasi:
  `pages/3_dashboard.py`, `pages/2_master.py`, `pages/8_explain.py`, `pages/9_history.py`,
  bukan "restart" penuh.

---

# 12. Antarmuka Streamlit

| Halaman     | Fungsi                                                     |
| ----------- | ---------------------------------------------------------- |
| Upload      | Upload CSV, validasi, registrasi batch, dan memulai proses |
| Pemeriksaan | Review pasangan kandidat dan memberi label                 |
| Master      | Melihat dan mengoreksi master record                       |
| Ringkasan   | Melihat metrik dan distribusi hasil                        |
| Latih Ulang | Melihat status/version model dan retraining                |
| Antrean     | Melihat pasangan yang membutuhkan review                   |
| Batch       | Meninjau batch baru sebelum digabung                       |
| Cakupan     | Melihat singleton dan pasangan yang belum masuk antrean    |
| Bukti       | Melihat alasan/field evidence dari keputusan               |
| Riwayat     | Melihat riwayat keputusan dan koreksi                      |

---

# 13. Alur Upload Data

Ketika data baru masuk:

```text
CSV
 ↓
Schema Validation
 ↓
Record ID
 ↓
Standardization
 ↓
Blocking
 ↓
Splink Scoring
 ↓
MATCH / REVIEW / NON_MATCH
 ↓
Review jika diperlukan
 ↓
Clustering
 ↓
Entity / Master Record
```

Sistem juga melakukan pemeriksaan seperti:

1. Validasi kolom.
2. Deteksi delimiter dan encoding.
3. Pemeriksaan format tanggal.
4. Registrasi batch.
5. Pemeriksaan file duplikat menggunakan SHA-256.
6. Pemrosesan batch dalam staging.
7. Review batch sebelum hasil digabungkan.

---

# 14. Perintah Pendukung

Perintah utama:

```powershell
python -m src.profiling
python -m src.standardize
python -m src.labels --silver-only
python -m src.blocking_benchmark --full
python -m src.splink_model --full
python -m src.labels --full
python -m src.clustering --full
python -m src.master_record
python -m src.evaluate
```

Perintah evaluasi dan maintenance:

```powershell
python -m src.threshold_eval --full
python -m src.eval_truth --full
python -m src.scenario_eval
python -m src.labels --promote
python -m src.close_gold_loop --all
python -m src.apply_gold
python -m src.model_lifecycle
python -m src.review_sample --band match
python -m src.stress_test --pairs 200
python -m src.batch_eval
python -m src.registry
python -m src.validate_upload <file.csv>
python -m src.incremental
python -m src.entity_correction --history
python -m src.export_linkage --band review
```

Perintah-perintah tersebut lebih ditujukan untuk development, evaluasi, dan maintenance daripada demo dasar.

---

# 15. Hasil Development Terakhir

Run development terakhir yang terdokumentasi:

```text
Run       : v20261005_145258
Scope     : full
Batch     : 9
Runtime   : 216,62 detik
```

| Metrik          |   Hasil |
| --------------- | ------: |
| Total record    |  51.555 |
| Candidate pairs | 311.294 |
| MATCH           |   3.401 |
| REVIEW          |      27 |
| NON_MATCH       | 307.866 |
| Auto-match rate |   1,09% |
| Review rate     | 0,0087% |
| Entity          |  48.380 |
| Merged records  |   3.175 |
| Entity terbesar |       5 |
| Unscored        |     417 |
| Smoke test      | 23 / 23 |

Hasil tersebut merupakan hasil pada dataset development dan **bukan jaminan performa pada dataset pelanggan lain**.

---

# 16. Evaluasi

Evaluasi dilakukan dalam beberapa lapisan:

| Lapisan  | Pertanyaan                                                       |
| -------- | ---------------------------------------------------------------- |
| Blocking | Apakah pasangan yang benar masuk sebagai kandidat?               |
| Linkage  | Bagaimana model memberikan keputusan terhadap pasangan kandidat? |
| Decision | Bagaimana threshold memengaruhi MATCH/REVIEW/NON_MATCH?          |
| Entity   | Apakah hasil clustering membentuk entity secara konsisten?       |

Pada development run terakhir:

* Blocking coverage terhadap pasangan referensi yang diuji: `3.366 / 3.366`.
* Edge MATCH yang terverifikasi device: `3.366`.
* Edge MATCH tanpa device truth: `35`.
* Entity yang mencampur dua device ID: `0`.

Angka ini hanya berlaku untuk eksperimen dan dataset yang digunakan.

---

# 17. Kualitas Label

Label manusia digunakan sebagai bagian dari evaluasi dan feedback.

Kondisi development terakhir:

| Sumber                      |        Jumlah |
| --------------------------- | ------------: |
| Gold labels                 |  245 pasangan |
| Match pada gold             |            17 |
| No-match pada gold          |           228 |
| Feedback                    | 342 keputusan |
| Review queue                |     150 baris |
| Review queue belum dilabeli |           148 |

Audit menemukan beberapa label manusia yang bertentangan dengan `device_id`.

Temuan penting:

> Nama dan email yang sama belum cukup untuk menyimpulkan bahwa dua record adalah customer yang sama.

Karena itu `device_id` dapat digunakan sebagai referensi evaluasi pada dataset development, tetapi tidak dianggap sebagai ground truth universal.

---

# 18. Interpretasi Threshold

Distribusi skor pada development run:

| Rentang       |  Jumlah |
| ------------- | ------: |
| ≤ 1e-5        | 261.530 |
| 1e-5 – 0,001  |  46.336 |
| 0,001 – 0,01  |      25 |
| 0,01 – 0,1    |       2 |
| 0,1 – 0,9     |       0 |
| ≥ 0,9         |   3.401 |

Distribusi tersebut bersifat sangat bimodal.

Tidak terdapat pasangan pada rentang `0,1–0,9`, sehingga threshold di antara rentang tersebut tidak memberikan perubahan berarti pada pembagian keputusan untuk dataset ini.

Karena itu angka threshold yang digunakan saat ini **tidak boleh dianggap sebagai threshold universal untuk dataset pelanggan lain**.

---

# 19. Keterbatasan

Beberapa hal yang perlu diperhatikan:

### Dataset development terbatas

Pengujian belum melampaui sekitar 51.500 record.

Kemampuan pada jutaan record masih perlu diuji.

### Device ID bukan ground truth mutlak

`device_id` pada dataset development memiliki hubungan yang sangat kuat dengan `customer_id`, sehingga evaluasi terhadap device ID mewarisi bias source dataset.

### Gold label terbatas

Gold set relatif kecil dan tidak sepenuhnya representatif terhadap seluruh kondisi data.

### Silver label bukan ground truth independen

Evaluasi silver tidak dapat digunakan sebagai bukti bahwa model memiliki performa sempurna karena silver label dibuat menggunakan heuristik.

### Pengujian typo bersifat sintetis

Recovery typo dilakukan pada data sintetis dan bukan bukti tingkat keberhasilan pada data customer nyata.

### Generalisasi belum terbukti

Model perlu diuji pada data dengan:

* missing value
* konflik informasi
* variasi sumber
* format berbeda
* typo berbeda
* distribusi customer yang berbeda

---

# 20. Troubleshooting

## `python` tidak dikenali

Pastikan Python sudah terinstall dan masuk ke PATH.

Coba:

```powershell
python --version
```

Jika tidak berhasil, install Python terlebih dahulu lalu buka terminal baru.

---

## `git` tidak dikenali

Cek:

```powershell
git --version
```

Jika tidak berhasil, install Git lalu buka terminal baru.

---

## PowerShell menolak `.venv\Scripts\Activate.ps1`

Gunakan:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Kemudian:

```powershell
.venv\Scripts\Activate.ps1
```

Perubahan ini hanya berlaku untuk sesi PowerShell tersebut.

---

## `streamlit` tidak dikenali

Jangan gunakan:

```powershell
streamlit run app.py
```

Gunakan:

```powershell
python -m streamlit run app.py
```

---

## `ModuleNotFoundError`

Pastikan virtual environment aktif:

```powershell
.venv\Scripts\Activate.ps1
```

Kemudian:

```powershell
pip install -r requirements.txt
```

---

## Dataset tidak ditemukan

Periksa:

1. Nama file.
2. Lokasi file.
3. Konfigurasi input di `src/config.py`.
4. Nama kolom dataset.
5. Hasil validasi:

```powershell
python -m src.validate_upload <file.csv>
```

Jangan langsung mengubah kode pipeline hanya karena path dataset berbeda.

---

## Model atau artifact tidak ditemukan

Periksa folder:

```text
models/
outputs/
data/processed/
data/labels/
```

Jika repository hasil clone tidak memiliki artifact yang dibutuhkan aplikasi, cek apakah artifact tersebut memang seharusnya dibuat saat pipeline dijalankan atau memang harus disediakan sebagai bagian dari environment demo.

Jangan membuat file dummy untuk melewati error.

---

# 21. Konfigurasi

Konfigurasi utama berada di:

```text
src/config.py
```

Hal yang perlu diperiksa sebelum mengubah konfigurasi:

* lokasi input
* `COLUMN_MAP`
* blocking rules
* threshold
* lokasi output
* lokasi model

Untuk demo biasa, **jangan mengubah konfigurasi jika tidak diperlukan**.

Jika dataset memiliki nama kolom berbeda, gunakan mekanisme pemetaan kolom yang tersedia daripada mengubah banyak bagian pipeline.

---

# 22. Development dan Production

Project ini berada pada tahap:

> **Prototype Internal Demonstration Tool**

Pipeline sudah mencakup:

* data validation
* standardization
* blocking
* probabilistic linkage dengan Splink
* decision classification
* human review
* clustering
* master record
* evaluation
* model versioning
* incremental processing

---

# 23. Credits

Teknologi utama:

* Python
* Splink
* DuckDB
* Pandas
* PyArrow
* Streamlit
* Jupyter

Dataset development:

`crm_50000_customers_dirty_v3.csv` dari Kaggle Customer 360.

Dataset digunakan untuk kebutuhan development dan evaluasi awal.

---

# 24. License

Repository ini belum mendefinisikan lisensi open-source khusus.

Jangan mengasumsikan repository dapat digunakan, dimodifikasi, atau didistribusikan ulang dengan ketentuan lisensi tertentu sebelum lisensi ditambahkan secara resmi.

---

# 25. Status

**Prototype Internal Demonstration Tool**

Versi repository saat ini ditujukan untuk demonstrasi dan pengembangan sistem deduplication berbasis probabilistic record linkage menggunakan Splink.

Untuk menjalankan demo dari laptop baru, gunakan urutan:

```powershell
git clone https://github.com/Boekanadip/dedupe-system-splink.git
cd dedupe-system-splink

python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

python tests/test_smoke.py

python -m streamlit run app.py
```

Jika seluruh langkah berhasil, aplikasi dapat digunakan melalui alamat lokal yang ditampilkan oleh Streamlit.

---

**Catatan singkat:**

* `pytest` mungkin belum terpasang di laptop kosong. Kalau `python tests/test_smoke.py` gagal dengan "No module named pytest" tapi Anda pakai file test Python biasa, tetap bisa pakai `python tests/test_smoke.py` (tanpa pytest). Test ini bisa dijalankan langsung dengan Python.
* `psutil` dibutuhkan `pages/4_retrain.py` tapi **tidak** ada di `requirements.txt`. Kalau muncul `ModuleNotFoundError: psutil`, jalankan: `pip install psutil`.
* Dataset raw **tidak ikut repo**. Wajib diletakkan manual di `data/raw/crm_50000_customers_dirty_v3.csv`. Artifact (`models/outputs/data/*`) dibuat otomatis oleh pipeline.
