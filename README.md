# System Dedupe with Splink

### Probabilistic Record Linkage menggunakan Splink, DuckDB, dan Streamlit

Sistem **CRM Entity Resolution & Deduplication** dirancang untuk mendeteksi, mengevaluasi, dan mengelola duplikasi data pelanggan menggunakan pendekatan *probabilistic record linkage*. Sistem menggabungkan standardisasi data, blocking, pemodelan probabilistik Splink, clustering, dan human review untuk mengidentifikasi record yang kemungkinan berasal dari pelanggan yang sama.

Dibangun menggunakan **Python, Splink, DuckDB, Pandas, dan Streamlit**, sistem ini menyediakan pipeline pemrosesan data serta antarmuka untuk mengelola hasil pencocokan, meninjau kandidat duplikat, mengevaluasi model, dan membentuk master record.

**Dataset pengembangan:** `crm_50000_customers_dirty_v3.csv` dari Kaggle Customer 360. Dataset ini digunakan untuk pengembangan dan evaluasi awal, bukan sebagai bukti kapasitas produksi.

---

## 1. Latar Belakang

Data pelanggan dari berbagai sumber sering kali memiliki informasi yang tidak konsisten. Satu pelanggan dapat tercatat lebih dari sekali akibat kesalahan penulisan nama, perbedaan format nomor telepon, alamat yang tidak seragam, atau informasi identitas yang tidak lengkap.

Sebagai contoh:

| Field         | Record A                                            | Record B                                            |
| ------------- | --------------------------------------------------- | --------------------------------------------------- |
| Nama          | John Smith                                          | Jhon Smith                                          |
| Email         | [john.smith@gmail.com](mailto:john.smith@gmail.com) | [john.smith@gmail.com](mailto:john.smith@gmail.com) |
| Nomor telepon | 08123456789                                         | +628123456789                                       |

Kedua record tersebut memiliki perbedaan pada nama dan format nomor telepon, tetapi kemungkinan merujuk pada pelanggan yang sama.

Pendekatan pencocokan persis (*exact matching*) tidak cukup untuk menangani kondisi tersebut. Oleh karena itu, sistem menggunakan pendekatan probabilistik untuk menilai tingkat kemiripan antardata, menentukan keputusan pencocokan, dan mengelompokkan record yang teridentifikasi sebagai entitas yang sama.

### Tujuan sistem

* Mengidentifikasi kandidat duplikat dari data pelanggan yang tidak konsisten.
* Mengurangi jumlah perbandingan melalui blocking.
* Menghasilkan skor probabilitas dan keputusan pencocokan.
* Menyediakan mekanisme human review untuk memvalidasi hasil yang belum meyakinkan.
* Membentuk entity dan master record dari hasil pencocokan.
* Mengevaluasi kualitas model dan stabilitas hasil ketika data bertambah.

---

## 2. Arsitektur Sistem

Sistem menggunakan pipeline bertahap untuk mengubah data pelanggan mentah menjadi entitas yang telah diidentifikasi.

```text
                 DATA INPUT
                     ⇣
             Schema Validation
                     ⇣
              Record ID Generation
                     ⇣
                     v
              Data Standardization
                     ⇣
             Blocking / Candidate
                 Generation
                     ⇣
             Splink Probabilistic
                 Record Linkage
                     ⇣
             Decision Classification
             ↙         |         ↘
          MATCH      REVIEW     NON_MATCH
             |         ⇣             |
             |    Human Review       |
             |         |             |
             +---------+-------------+
                       ⇣
                 Clustering
                       ⇣
                 Entity ID
                       ⇣
                 Master Record
                       ⇣
             Evaluation & Feedback
```

### Komponen utama

| Komponen                    | Fungsi                                                                                                                 |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **Data validation**         | Memeriksa kesesuaian skema dan kelengkapan kolom yang diperlukan.                                                      |
| **Record ID generation**    | Menghasilkan identifier internal untuk setiap record dan menjaga keterlacakan lintas batch.                            |
| **Standardization**         | Menormalisasi nilai tanpa menimpa data asli.                                                                           |
| **Blocking**                | Menghasilkan pasangan kandidat menggunakan 12 aturan blocking untuk mengurangi ruang pencarian.                        |
| **Splink**                  | Melakukan probabilistic record linkage menggunakan pendekatan Fellegi-Sunter dan parameter yang dipelajari melalui EM. |
| **Decision classification** | Mengelompokkan pasangan menjadi MATCH, REVIEW, atau NON_MATCH berdasarkan kebijakan keputusan.                         |
| **Human review**            | Memvalidasi kandidat yang memerlukan pemeriksaan manual dan menyimpan label hasil review.                              |
| **Clustering**              | Mengelompokkan record yang dinyatakan cocok menjadi entity menggunakan union-find.                                     |
| **Master record**           | Menghasilkan satu representasi utama untuk setiap entity beserta keterkaitan ke record sumber.                         |
| **Evaluation & feedback**   | Mengukur kualitas proses dan memanfaatkan label manusia untuk evaluasi serta pengembangan model.                       |

### Perbedaan identifier

Sistem membedakan tiga jenis identifier yang memiliki fungsi berbeda.

| Identifier    | Fungsi                                                                                                               |
| ------------- | -------------------------------------------------------------------------------------------------------------------- |
| `record_id`   | Identitas internal untuk setiap baris data yang diproses oleh sistem.                                                |
| `customer_id` | Identifier yang berasal dari sistem sumber. Nilainya tidak dianggap sebagai kebenaran identitas pelanggan.           |
| `entity_id`   | Identifier hasil resolusi yang merepresentasikan kelompok record yang diperkirakan berasal dari pelanggan yang sama. |

---

## 3. Teknologi yang Digunakan

| Teknologi        | Peran                                                                |
| ---------------- | -------------------------------------------------------------------- |
| Python           | Bahasa pemrograman utama dan orkestrasi pipeline.                    |
| Splink 4.0.17    | Probabilistic record linkage dan pemodelan pencocokan.               |
| DuckDB           | Mesin pemrosesan data lokal untuk mendukung proses record linkage.   |
| Pandas           | Manipulasi, standardisasi, dan analisis data.                        |
| PyArrow          | Penyimpanan dan pertukaran data dalam format Parquet.                |
| Streamlit        | Antarmuka interaktif untuk demonstrasi dan pengelolaan hasil dedupe. |
| Jupyter Notebook | Eksperimen, demonstrasi, dan profiling.                              |

Sistem menggunakan DuckDB yang berjalan di dalam proses sehingga tidak memerlukan server database terpisah untuk menjalankan demonstrasi.

---

## 4. Persyaratan dan Instalasi

### Persyaratan

* Python 3.10 atau lebih baru.
* Windows, Linux, atau macOS.
* Git.
* Dataset pengembangan dalam format CSV.
* RAM dan kapasitas penyimpanan yang memadai sesuai ukuran data yang diproses.

Pengembangan dilakukan menggunakan Python 3.14. Kompatibilitas dengan versi Python dan sistem operasi lain tetap perlu diverifikasi.

### Instalasi

Clone repository:

```powershell
git clone https://github.com/Boekanadip/dedupe-system-splink.git
cd dedupe-system-splink
```

Buat virtual environment:

```powershell
python -m venv .venv
```

Aktifkan environment:

```powershell
.venv\Scripts\Activate.ps1
```

Instal dependensi:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Tempatkan dataset sesuai konfigurasi input pada project. Pastikan skema dataset memenuhi kolom yang diwajibkan oleh pipeline sebelum menjalankan proses.

---

## 5. Menjalankan Sistem

### Quick Start

Jalankan pipeline lengkap dengan pelatihan model baru:

```powershell
python -m src.run_all
```

Gunakan model yang sudah tersimpan tanpa melakukan pelatihan ulang:

```powershell
python -m src.run_all --reuse-model latest
```

Jalankan smoke test:

```powershell
python tests/test_smoke.py
```

Jalankan aplikasi Streamlit:

```powershell
streamlit run app.py
```

Secara default, sistem menggunakan model tersimpan ketika memproses data baru. Pelatihan ulang dilakukan secara eksplisit melalui proses retraining, bukan otomatis setiap kali ada data yang masuk.

**Catatan:** waktu eksekusi yang tercantum dalam hasil eksperimen merupakan pengukuran pada lingkungan pengembangan dan dapat berbeda bergantung pada perangkat keras, ukuran data, serta konfigurasi yang digunakan.

---

## 6. Struktur Direktori

Berikut gambaran struktur modul dan penyimpanan sistem.

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
│   ├── standardize.py
│   ├── splink_model.py
│   ├── clustering.py
│   ├── labels.py
│   ├── apply_gold.py
│   ├── close_gold_loop.py
│   ├── entity_correction.py
│   ├── evaluate.py
│   ├── scenario_eval.py
│   ├── incremental.py
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
├── notebooks/
├── .streamlit/
│   └── config.toml
├── requirements.txt
├── .gitignore
└── README.md
```

Daftar modul `src/` di atas bersifat ringkasan. Seluruh modul yang dapat dijalankan sebagai CLI terdaftar pada bagian [Pipeline dan Perintah Pendukung](#7-pipeline-dan-perintah-pendukung).

### Modul utama

| Modul                  | Tanggung jawab                                                                          |
| ---------------------- | --------------------------------------------------------------------------------------- |
| `config.py`            | Konfigurasi path, pemetaan kolom, aturan blocking, dan threshold.                       |
| `standardize.py`       | Standardisasi data, pembuatan kolom standar, blocking key, dan deteksi format tanggal.  |
| `splink_model.py`      | Pelatihan model Splink, pencocokan, scoring, dan klasifikasi keputusan.                 |
| `clustering.py`        | Pengelompokan record MATCH menjadi entity menggunakan union-find.                       |
| `labels.py`            | Pembuatan silver label, pengelolaan review queue, dan promosi label menjadi gold label. |
| `apply_gold.py`        | Penerapan keputusan berdasarkan gold label dengan pemeriksaan aturan pengaman.          |
| `close_gold_loop.py`   | Menggabungkan proses promosi label, feedback, penerapan keputusan, dan evaluasi.        |
| `entity_correction.py` | Koreksi entity melalui operasi split dan merge beserta pencatatan riwayat.              |
| `evaluate.py`          | Evaluasi pada tingkat blocking, linkage, decision, dan entity.                          |
| `scenario_eval.py`     | Pengujian skenario pencocokan seperti typo, email sama, dan kegagalan blocking.         |
| `incremental.py`       | Pemrosesan batch baru tanpa menjalankan ulang seluruh pipeline.                         |
| `run_all.py`           | Orkestrasi tahapan pipeline secara berurutan.                                           |

### Pengelolaan file

Data mentah, hasil pemrosesan, label, dan output eksperimen disimpan secara lokal dan tidak disertakan dalam repository.

* `data/raw/`: dataset mentah per batch.
* `data/processed/`: data hasil standardisasi dalam format Parquet.
* `data/labels/`: review queue dan gold label.
* `outputs/`: hasil prediksi, entity map, dan laporan evaluasi.
* `models/`: konfigurasi dan parameter model beserta metadata versi.

File data berukuran besar dan data pelanggan tidak seharusnya diunggah ke repository tanpa pemeriksaan keamanan dan kebutuhan yang jelas.

### Dokumen lokal (tidak dikirim ke GitHub)

Dokumen internal — `PRD.md`, `DESIGN.md`, `AGENTS.md`, `MASTER_CONTEXT.md.txt`, folder `docs/`, dan `.opencode/skills/` — hanya ada di disk lokal dan diabaikan via `.gitignore`. File-file tersebut tidak ikut ter-push ke GitHub, tetapi riwayat commit lama masih menyimpannya (lihat `git log --diff-filter=D`).

---

## 7. Pipeline dan Perintah Pendukung

Pipeline utama menjalankan tahapan berikut secara berurutan.

| Tahap              | Perintah                                  | Output utama                              |
| ------------------ | ----------------------------------------- | ----------------------------------------- |
| Profiling          | `python -m src.profiling`                 | `outputs/profiling_summary.json`          |
| Standardisasi      | `python -m src.standardize`               | `data/processed/crm_standardized.parquet` |
| Silver labeling    | `python -m src.labels --silver-only`      | `data/labels/silver_pairs.csv`            |
| Blocking benchmark | `python -m src.blocking_benchmark --full` | `outputs/blocking_benchmark.csv`          |
| Splink model       | `python -m src.splink_model --full`       | `outputs/splink_predictions.parquet`      |
| Review queue       | `python -m src.labels --full`             | `data/labels/review_queue.csv`            |
| Clustering         | `python -m src.clustering --full`         | `outputs/entity_map.parquet`              |
| Master record      | `python -m src.master_record`             | `outputs/master_customers.parquet`        |
| Evaluasi           | `python -m src.evaluate`                  | `outputs/evaluation_report.json`          |

### Perintah tambahan

```powershell
# Evaluasi threshold
python -m src.threshold_eval --full

# Evaluasi skenario
python -m src.scenario_eval

# Promosi label review menjadi gold label
python -m src.labels --promote

# Menjalankan feedback loop
python -m src.close_gold_loop --all

# Menerapkan gold label dalam mode dry-run
python -m src.apply_gold

# Melihat daftar versi model
python -m src.model_lifecycle

# Mengambil sampel pasangan untuk review
python -m src.review_sample --band match

# Menguji recovery terhadap duplikat sintetis
python -m src.stress_test --pairs 200

# Evaluasi stabilitas entity antarbatch
python -m src.batch_eval

# Melihat registry batch dan record ID
python -m src.registry

# Memvalidasi dataset sebelum registrasi
python -m src.validate_upload file.csv

# Memproses batch baru
python -m src.incremental

# Melihat riwayat koreksi entity
python -m src.entity_correction --history

# Evaluasi terhadap device_id (jalur independen dari silver label)
python -m src.eval_truth --full

# Ekspor bukti keputusan per pasangan (bahan explainability)
python -m src.export_linkage --band review
```

---

## 8. Antarmuka Streamlit

Sistem menyediakan antarmuka Streamlit untuk menjalankan proses dedupe, meninjau hasil pencocokan, mengelola entity, dan memantau evaluasi.

Jalankan aplikasi:

```powershell
streamlit run app.py
```

### Fitur aplikasi

| Halaman                   | Fungsi                                                                                         |
| ------------------------- | ---------------------------------------------------------------------------------------------- |
| Upload (`app.py`)         | Mengunggah CSV, memvalidasi skema, mendaftarkan batch, dan memulai pemrosesan.                 |
| Review (`1_review`)       | Meninjau pasangan kandidat dan memberikan label `match` atau `no_match`.                       |
| Master (`2_master`)       | Menelusuri master record, memperbaiki nilai, dan menandai kesalahan penggabungan.              |
| Dashboard (`3_dashboard`) | Menampilkan metrik seperti auto-match rate, review rate, distribusi skor, dan aktivitas batch. |
| Retrain (`4_retrain`)     | Mengelola status model, membandingkan versi, melakukan rollback, dan mengeksplorasi threshold. |
| Queue (`5_queue`)         | Memantau cakupan band REVIEW dan pasangan yang telah disampel.                                 |
| Batch (`6_batch`)         | Meninjau proposal batch baru sebelum digabungkan atau ditolak.                                 |
| Gaps (`7_gaps`)           | Menampilkan singleton entity dan pasangan REVIEW yang belum masuk antrean.                     |
| Explain (`8_explain`)     | Menampilkan bukti pencocokan per field, termasuk bobot m/u dan gamma.                          |
| History (`9_history`)     | Menelusuri riwayat keputusan pasangan, record, serta koreksi entity.                           |

### Alur upload data

1. Pengguna mengunggah file CSV.
2. Sistem memvalidasi kolom wajib dan kolom yang diperlukan untuk blocking.
3. Sistem mendeteksi delimiter dan encoding serta meminta konfirmasi format tanggal apabila ambigu.
4. File baru disimpan setelah pengguna menekan tombol registrasi.
5. Sistem menggunakan SHA-256 untuk menolak file yang identik dengan file yang sudah terdaftar.
6. Batch baru diproses dalam tahap staging.
7. Hasil batch ditinjau melalui halaman Batch sebelum digabungkan ke data yang telah dikelola sistem.

---

## 9. Evaluasi dan Hasil Eksperimen

Evaluasi dilakukan untuk mengukur performa pencocokan dan konsistensi hasil pengelompokan, bukan hanya berdasarkan satu metrik keseluruhan.

### Hasil run terakhir

Berdasarkan run terakhir yang didokumentasikan, sistem memproses **51.555 baris dari 9 batch**, menggunakan model `v20261001_141528`.

| Metrik                                           |                Hasil |
| ------------------------------------------------ | -------------------: |
| Total record                                     |               51.555 |
| Jumlah batch                                     |                    9 |
| Pasangan kandidat dari 12 aturan blocking        |              311.294 |
| Keputusan MATCH                                  |                3.401 |
| Keputusan REVIEW                                 |               45.963 |
| Keputusan NON_MATCH                              |              261.930 |
| Auto-match rate                                  |                1,09% |
| Review rate                                      |               14,77% |
| Non-match rate                                   |               84,14% |
| Entity hasil clustering                          |               48.380 |
| Device-truth yang berada dalam satu entity       | 3.366 / 3.366 (100%) |
| Entity yang mencampur dua device ID              |                    0 |
| Salah penggabungan lintas batch yang teramati    |                    0 |
| Perubahan entity ID lama ketika batch baru masuk |                    0 |
| Recovery pada 200 duplikat sintetis ber-typo     |            200 / 200 |
| Smoke test                                       |         20 / 20 PASS |

Angka di atas merupakan hasil dari eksperimen yang didokumentasikan dan tidak boleh langsung dianggap sebagai estimasi performa pada dataset pelanggan lain.

### Evaluasi empat lapis

| Lapisan      | Fokus evaluasi                                                           | Hasil yang dilaporkan                                                                                            |
| ------------ | ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| **Blocking** | Memeriksa apakah pasangan yang dianggap benar tersedia sebagai kandidat. | 3.366 / 3.366; coverage 100% pada pasangan referensi yang diuji.                                                 |
| **Linkage**  | Mengukur keputusan model terhadap pasangan kandidat.                     | 3.366 pasangan di atas threshold dan 0 false merge pada evaluasi berbasis device-truth.                          |
| **Decision** | Memantau distribusi keputusan berdasarkan threshold.                     | 1,09% auto-match dan 14,77% review.                                                                              |
| **Entity**   | Memeriksa konsistensi hasil pengelompokan.                               | 3.366 pasangan referensi tergabung dan tidak ditemukan pasangan referensi yang terpecah dalam evaluasi tersebut. |

Evaluasi tersebut memiliki cakupan dan keterbatasan yang berbeda. Hasil pada tingkat blocking tidak otomatis membuktikan kualitas model, sedangkan hasil clustering tidak dengan sendirinya membuktikan bahwa seluruh entity mewakili orang yang benar-benar sama.

---

## 10. Model Lifecycle dan Feedback

Sistem mendukung pengelolaan versi model untuk menjaga keterlacakan konfigurasi dan hasil evaluasi.

Contoh struktur penyimpanan:

```text
models/
├── v20261001_141528/
│   ├── model.json
│   ├── metadata.json
│   ├── thresholds.json
│   └── evaluation.json
└── latest.json
```

| File              | Isi                                                                          |
| ----------------- | ---------------------------------------------------------------------------- |
| `model.json`      | Parameter model Splink yang telah dilatih, termasuk parameter m/u per level. |
| `metadata.json`   | Informasi data latih, seed, versi library, dan runtime.                      |
| `thresholds.json` | Kebijakan threshold yang digunakan dalam evaluasi versi model.               |
| `evaluation.json` | Ringkasan jumlah dan distribusi keputusan pada run terkait.                  |
| `latest.json`     | Pointer ke versi model aktif.                                                |

### Kebijakan model

* Data baru secara default menggunakan model yang sudah tersedia.
* Retraining dilakukan sebagai tindakan eksplisit.
* Setiap versi model memiliki metadata dan hasil evaluasi.
* Perubahan threshold perlu dievaluasi karena dapat mengubah distribusi keputusan.
* Feedback manusia disimpan secara append-only dengan identifikasi pasangan dan versi model.
* Model dapat dibandingkan dan dipulihkan ke versi sebelumnya melalui mekanisme lifecycle.

Pemisahan antara model dan kebijakan keputusan diperlukan agar perubahan threshold tidak disalahartikan sebagai perubahan parameter hasil pelatihan.

---

## 11. Incremental Deduplication

Sistem menyediakan mekanisme untuk menghubungkan batch baru dengan data yang telah diproses sebelumnya tanpa menjalankan ulang seluruh pipeline.

Tujuannya adalah mengurangi pekerjaan berulang ketika jumlah data terus bertambah, sekaligus menjaga konsistensi entity yang sudah terbentuk.

Hasil pengujian yang didokumentasikan:

* Pemrosesan incremental sekitar 5 detik untuk batch berisi 100 baris.
* Pemrosesan penuh 97 detik (`outputs/run_summary.json`, run `v20261001_141528`, reuse model).
* Tidak ditemukan perubahan entity ID lama ketika batch baru ditambahkan dalam eksperimen tersebut.

Hasil ini merupakan pengukuran pada lingkungan dan skenario tertentu. Performa dapat berubah berdasarkan jumlah record, jumlah kandidat yang dihasilkan, aturan blocking, serta karakteristik data baru.

---

## 12. Batasan dan Interpretasi Hasil

Hasil eksperimen harus dibaca bersama dengan keterbatasan dataset, label referensi, dan asumsi yang digunakan.

### 12.1 Keterbatasan ground truth

`device_id` digunakan sebagai referensi evaluasi, tetapi bukan bukti independen mengenai identitas pelanggan.

Pada dataset yang digunakan, 48.200 device ID membentuk 48.200 grup `customer_id`, tanpa grup yang memiliki lebih dari satu device ID. Kondisi tersebut membatasi kemampuan dataset untuk menguji kasus duplikasi fuzzy yang lebih kompleks.

Dengan demikian, kesesuaian terhadap device-truth menunjukkan konsistensi terhadap referensi yang tersedia, bukan jaminan bahwa model dapat mengidentifikasi seluruh duplikat pada data pelanggan nyata.

### 12.2 Keterbatasan gold label

Gold set yang tersedia berisi 242 pasangan:

* 14 pasangan `match`.
* 228 pasangan `no_match`.

Precision yang terukur adalah 1,0, sedangkan recall adalah 0,43 pada evaluasi tersebut.

Sebanyak 8 pasangan positif tidak dipaksa untuk digabungkan karena konflik device ID dan aturan pengaman pada `apply_gold.py`.

Ukuran gold set yang terbatas, khususnya jumlah pasangan positif, membuat hasil evaluasi belum cukup untuk digeneralisasikan ke berbagai kondisi data.

### 12.3 Silver label bukan ground truth independen

Nilai F1 sebesar 1,0 pada evaluasi silver tidak dapat dianggap sebagai bukti bahwa model memiliki performa sempurna.

Silver label dibuat menggunakan heuristik yang berkaitan dengan proses evaluasi. Oleh sebab itu, hasil tersebut berpotensi mencerminkan kesesuaian model terhadap aturan pembentukan label, bukan kemampuan generalisasi terhadap kebenaran identitas pelanggan.

### 12.4 Asumsi dan parameter

Beberapa parameter yang digunakan masih berupa asumsi:

* `M_ELSE_LEVEL_FLOOR = 0.05`.
* `LAMBDA_RECALL_ASSUMPTION = 0.7`.
* `MATCH_THRESHOLD = 0.9`.
* `REVIEW_THRESHOLD = 1e-10`.

Threshold belum divalidasi menggunakan gold set dua kelas yang cukup representatif. Evaluasi ulang diperlukan ketika dataset, aturan comparison, atau kebijakan keputusan berubah.

### 12.5 Pengujian typo bersifat sintetis

Hasil recovery 200 dari 200 pasangan merupakan pengujian terhadap data sintetis yang dimodifikasi di dalam memori.

Hasil tersebut berguna untuk menguji perilaku pipeline dalam skenario yang telah dirancang, tetapi bukan bukti tingkat keberhasilan pada data pelanggan nyata yang memiliki variasi kesalahan penulisan lebih beragam.

### 12.6 Keterbatasan skalabilitas

Sistem telah memiliki benchmark blocking dan pengujian incremental. Namun, pengujian yang didokumentasikan belum melampaui sekitar 51.500 baris.

Kemampuan menangani jutaan record, performa pada distribusi data berbeda, serta kebutuhan infrastruktur untuk skala lebih besar masih perlu diuji secara terpisah.

---

## 13. Pengembangan Selanjutnya

Beberapa area yang dapat dikembangkan untuk meningkatkan kemampuan sistem meliputi:

* Memperluas gold set dengan pasangan positif dan negatif yang lebih beragam.
* Menguji kualitas model pada dataset yang memiliki ground truth independen.
* Mengevaluasi threshold berdasarkan trade-off precision, recall, dan kebutuhan review.
* Menguji skenario konflik informasi, missing value, serta duplikasi lintas sumber.
* Memperluas cakupan koreksi entity yang sudah tersedia (`entity_correction`) dan memvalidasi ulang hasil clustering setelah setiap koreksi.
* Menguji stabilitas hasil incremental ketika volume dan variasi data meningkat.
* Memperluas benchmark performa untuk mengukur kemampuan pemrosesan pada ukuran data yang lebih besar.

Prioritas pengembangan perlu ditentukan berdasarkan hasil evaluasi dan karakteristik data yang akan ditangani.

---


## 14. Status Proyek

**Status: Prototype Internal Demonstration Tool**

Sistem telah memiliki pipeline record linkage, mekanisme review, pembentukan entity, master record, evaluasi, model versioning, dan pemrosesan incremental.

Hasil eksperimen awal menunjukkan bahwa komponen-komponen tersebut dapat dijalankan secara terintegrasi pada dataset pengembangan yang digunakan.

Namun, kualitas generalisasi model, keandalan pada data pelanggan yang lebih beragam, dan skalabilitas pada volume yang jauh lebih besar masih memerlukan validasi lebih lanjut.

Sistem ini ditujukan untuk pengembangan, eksperimen, evaluasi, dan demonstrasi kemampuan deduplication. Hasilnya belum dapat dianggap sebagai jaminan kesiapan produksi atau akurasi pada seluruh jenis data pelanggan.
