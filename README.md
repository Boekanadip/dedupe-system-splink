# System Dedupe with Splink

### Probabilistic Record Linkage menggunakan Splink, DuckDB, dan Streamlit

Sistem **CRM Entity Resolution & Deduplication** untuk mendeteksi, mengevaluasi, dan mengelola duplikasi data pelanggan menggunakan pendekatan *probabilistic record linkage*. Pipeline menggabungkan standardisasi data, blocking, pemodelan probabilistik Splink, clustering, dan human review.

Dibangun menggunakan **Python, Splink, DuckDB, Pandas, dan Streamlit**.

**Dataset pengembangan:** `crm_50000_customers_dirty_v3.csv` (Kaggle Customer 360) ditambah 8 batch tambahan untuk uji incremental. Dipakai untuk pengembangan dan evaluasi awal, bukan sebagai bukti kapasitas produksi.

> **Dokumen pengguna non-teknis:** lihat [`PANDUAN.md`](PANDUAN.md). Dokumen ini untuk pembaca teknis.

---

## 1. Latar Belakang

Data pelanggan dari berbagai sumber sering tidak konsisten. Satu pelanggan dapat tercatat lebih dari sekali akibat kesalahan penulisan nama, perbedaan format nomor telepon, alamat yang tidak seragam, atau informasi identitas yang tidak lengkap.

| Field         | Record A                   | Record B                   |
| ------------- | -------------------------- | -------------------------- |
| Nama          | John Smith                 | Jhon Smith                 |
| Email         | john.smith@gmail.com      | john.smith@gmail.com       |
| Nomor telepon | 08123456789                | +628123456789              |

Pendekatan pencocokan persis (*exact matching*) tidak cukup. Sistem menggunakan pendekatan probabilistik untuk menilai tingkat kemiripan, menentukan keputusan pencocokan, dan mengelompokkan record yang diperkirakan berasal dari pelanggan yang sama.

### Tujuan sistem

* Mengidentifikasi kandidat duplikat dari data pelanggan yang tidak konsisten.
* Mengurangi jumlah perbandingan melalui blocking.
* Menghasilkan skor probabilitas dan keputusan pencocokan.
* Menyediakan mekanisme human review untuk memvalidasi hasil yang belum meyakinkan.
* Membentuk entity dan master record dari hasil pencocokan.
* Mengevaluasi kualitas model dan stabilitas hasil ketika data bertambah.

---

## 2. Arsitektur Sistem

```text
                 DATA INPUT
                     ⇣
             Schema Validation
                     ⇣
              Record ID Generation
                     ⇣
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
| **Data validation**         | Memeriksa skema, kelengkapan kolom, delimiter, dan encoding.                                                           |
| **Record ID generation**    | Menghasilkan `record_id` internal dan menjaga keterlacakan lintas batch.                                                |
| **Standardization**         | Menormalisasi nilai ke kolom `*_std` tanpa menimpa data asli.                                                           |
| **Blocking**                | Menghasilkan pasangan kandidat menggunakan 12 aturan blocking.                                                          |
| **Splink**                  | Probabilistic record linkage dengan pendekatan Fellegi-Sunter; parameter m/u dipelajari melalui EM.                   |
| **Decision classification** | Menggolongkan pasangan menjadi MATCH, REVIEW, atau NON_MATCH.                                                           |
| **Human review**            | Memvalidasi kandidat yang ambigu dan menyimpan label hasil review.                                                       |
| **Clustering**              | Mengelompokkan record MATCH menjadi entity menggunakan union-find.                                                     |
| **Master record**           | Menghasilkan satu representasi utama per entity beserta keterkaitan ke record sumber.                                   |
| **Evaluation & feedback**   | Mengukur kualitas proses dan memanfaatkan label manusia untuk evaluasi serta perbaikan model.                               |

### Perbedaan identifier

| Identifier    | Fungsi                                                                                                               |
| ------------- | -------------------------------------------------------------------------------------------------------------------- |
| `record_id`   | Identitas internal untuk setiap baris data yang diproses sistem.                                                     |
| `customer_id` | Identifier dari sistem sumber. **Tidak dianggap kebenaran identitas pelanggan.**                                     |
| `entity_id`   | Identifier hasil resolusi: kelompok record yang diperkirakan berasal dari pelanggan yang sama.                     |
| `device_id`   | Kanal verifikasi opsional yang **tidak pernah dipakai** sebagai blocking key maupun field pembanding.                  |

---

## 3. Teknologi yang Digunakan

| Teknologi        | Peran                                                                |
| ---------------- | --------------------------------------------------------------------- |
| Python           | Bahasa utama dan orkestrasi pipeline. Dikembangkan pada Python 3.14.  |
| Splink 4.0.17    | Probabilistic record linkage dan pemodelan pencocokan.                |
| DuckDB           | Mesin pemrosesan data lokal untuk proses record linkage.              |
| Pandas           | Manipulasi, standardisasi, dan analisis data.                        |
| PyArrow          | Penyimpanan dan pertukaran data dalam format Parquet.                |
| Streamlit        | Antarmuka interaktif untuk dedupe dan review.                         |
| Jupyter Notebook | Eksperimen, demonstrasi, dan profiling.                              |

---

## 4. Persyaratan dan Instalasi

* Python 3.10 atau lebih baru.
* Windows, Linux, atau macOS.
* Git.
* Dataset pengembangan dalam format CSV.

### Instalasi

```powershell
git clone https://github.com/Boekanadip/dedupe-system-splink.git
cd dedupe-system-splink

python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
```

Letakkan dataset sesuai konfigurasi input pada project. Pastikan skema dataset memenuhi kolom yang diwajibkan pipeline sebelum menjalankan proses.

---

## 5. Menjalankan Sistem

```powershell
# Pipeline lengkap dengan pelatihan model baru
python -m src.run_all

# Pipeline menggunakan model tersimpan
python -m src.run_all --reuse-model latest

# Smoke test (read-only: hanya membaca artifact, tidak menulis outputs/)
python tests/test_smoke.py

# Aplikasi Streamlit
streamlit run app.py
```

Secara default sistem memakai model tersimpan saat memproses data baru. Training ulang dilakukan eksplisit, bukan otomatis setiap ada data masuk.

---

## 6. Struktur Direktori

```text
.
├── app.py                    # Halaman Upload
├── pages/
│   ├── 1_review.py           # Pemeriksaan Pasangan
│   ├── 2_master.py           # Master Customer
│   ├── 3_dashboard.py        # Ringkasan
│   ├── 4_retrain.py          # Latih Ulang Model
│   ├── 5_queue.py            # Antrean Pemeriksaan
│   ├── 6_batch.py            # Batch
│   ├── 7_gaps.py             # Cakupan & Kekurangan
│   ├── 8_explain.py          # Bukti Pencocokan
│   └── 9_history.py          # Riwayat
│
├── src/
│   ├── config.py             # Path, COLUMN_MAP, aturan blocking, threshold
│   ├── validate_upload.py    # Validasi skema + deteksi delimiter/encoding
│   ├── profiling.py          # Ringkasan data mentah
│   ├── standardize.py        # Kolom *_std, blocking key, deteksi format tanggal
│   ├── registry.py           # Registry batch & kepemilikan record_id
│   ├── blocking_benchmark.py # Benchmark aturan blocking
│   ├── splink_model.py       # Training, scoring, klasifikasi keputusan
│   ├── clustering.py         # Union-find record MATCH -> entity
│   ├── master_record.py      # Master record per entity
│   ├── labels.py             # Silver label, review queue, promosi gold label
│   ├── feedback.py           # Penyimpanan keputusan manusia
│   ├── apply_gold.py         # Terapkan gold label + aturan pengaman
│   ├── close_gold_loop.py    # Promosi -> feedback -> apply -> evaluasi
│   ├── entity_correction.py  # Koreksi entity (split/merge) + riwayat
│   ├── evaluate.py           # Evaluasi 4 lapis
│   ├── eval_truth.py         # Evaluasi terhadap device_id
│   ├── threshold_eval.py     # Kurva precision/recall per threshold
│   ├── scenario_eval.py      # Skenario: typo, email sama, blocking gagal
│   ├── export_linkage.py     # Ekspor bukti keputusan per pasangan
│   ├── review_sample.py      # Sampling pasangan untuk review
│   ├── stress_test.py        # Uji recovery duplikat sintetis
│   ├── batch_eval.py         # Stabilitas entity antar batch
│   ├── incremental.py        # Pemrosesan batch baru
│   ├── model_lifecycle.py    # Versi model, perbandingan, rollback
│   ├── ui.py                 # Helper UI bersama + kamus kosakata
│   └── run_all.py            # Orkestrasi pipeline
│
├── data/{raw,processed,labels}/
├── models/
├── outputs/
├── tests/test_smoke.py       # 23 invariant, tanpa framework
├── notebooks/
├── .streamlit/config.toml
├── requirements.txt
├── PANDUAN.md                # Panduan pengguna non-teknis
└── README.md
```

### Pengelolaan file

* `data/raw/` — dataset mentah per batch.
* `data/processed/` — hasil standardisasi (Parquet).
* `data/labels/` — silver label, review queue, gold label, dan pasangan yang markah masih diragukan.
* `outputs/` — prediksi, entity map, dan laporan evaluasi.
* `models/` — parameter model, metadata, thresholds, dan evaluasi per versi.

File data berukuran besar dan data pelanggan tidak seharusnya diunggah ke repository tanpa pemeriksaan keamanan.

### Dokumen lokal (tidak dikirim ke GitHub)

Dokumen internal — `PRD.md`, `DESIGN.md`, `AGENTS.md`, `MASTER_CONTEXT.md.txt`, folder `docs/`, dan `.opencode/skills/` — hanya ada di disk lokal dan diabaikan via `.gitignore`. Riwayat commit lama masih menyimpannya (lihat `git log --diff-filter=D`).

---

## 7. Pipeline dan Perintah Pendukung

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
python -m src.threshold_eval --full              # kurva precision/recall
python -m src.threshold_eval --source silver     # paksa sumber label
python -m src.eval_truth --full                  # evaluasi device_id
python -m src.scenario_eval
python -m src.labels --promote
python -m src.close_gold_loop --all
python -m src.apply_gold
python -m src.model_lifecycle
python -m src.review_sample --band match
python -m src.stress_test --pairs 200
python -m src.batch_eval
python -m src.registry
python -m src.validate_upload file.csv
python -m src.incremental
python -m src.entity_correction --history
python -m src.export_linkage --band review
```

---

## 8. Antarmuka Streamlit

| Halaman                   | Fungsi                                                                                         |
| ------------------------- | ---------------------------------------------------------------------------------------------- |
| Upload (`app.py`)         | Mengunggah CSV, memvalidasi skema, mendaftarkan batch, memulai pemrosesan.                      |
| Pemeriksaan (`1_review`)  | Meninjau pasangan kandidat dan memberi label `match` / `no_match`.                              |
| Master (`2_master`)       | Menelusuri master record, memperbaiki nilai, menandai salah gabung/salah pecah.                 |
| Ringkasan (`3_dashboard`) | Metrik keputusan, distribusi skor, dan aktivitas batch.                                          |
| Latih ulang (`4_retrain`) | Status model, perbandingan versi, rollback, eksplorasi threshold.                               |
| Antrean (`5_queue`)       | Cakupan band REVIEW dan pasangan yang sudah disampel.                                           |
| Batch (`6_batch`)         | Review proposal batch baru sebelum digabung atau ditolak.                                       |
| Cakupan (`7_gaps`)        | Singleton entity dan pasangan REVIEW yang belum masuk antrean.                                  |
| Bukti (`8_explain`)       | Bukti pencocokan per field: bobot m/u, gamma, dan perbandingan nilai.                           |
| Riwayat (`9_history`)     | Riwayat keputusan pasangan, record, dan koreksi entity.                                          |

Semua halaman memakai `page_guide()` dari `src/ui.py` sehingga menampilkan expander "Apa yang harus saya lakukan di halaman ini?", dan `monitoring_sidebar()` sehingga model aktif, jumlah batch, dan antrian review terlihat di setiap halaman.

### Alur upload data

1. Pengguna mengunggah file CSV.
2. Sistem memvalidasi kolom wajib dan kolom blocking.
3. Sistem mendeteksi delimiter dan encoding, serta meminta konfirmasi format tanggal bila ambigu.
4. SHA-256 menolak file yang identik dengan batch terdaftar.
5. Batch baru diproses dalam tahap staging.
6. Hasil batch ditinjau di halaman Batch sebelum digabungkan.

---

## 9. Hasil Run Terakhir

Run `v20261005_145258`, scope `full`, 9 batch, 216,62 detik (`outputs/run_summary.json`).

| Metrik                                    |       Hasil |
| ----------------------------------------- | -----------: |
| Total record                              |      51.555 |
| Jumlah batch                              |            9 |
| Pasangan kandidat dari 12 aturan blocking |     311.294 |
| Keputusan MATCH                           |       3.401 |
| Keputusan REVIEW                          |          27 |
| Keputusan NON_MATCH                       |     307.866 |
| Auto-match rate                           |       1,09% |
| Review rate                               |     0,0087% |
| Entity hasil clustering                   |      48.380 |
| Record yang menyatu                       |       3.175 |
| Entity terbesar                           |            5 |
| Record tanpa skor (unscored)              |          417 |
| Device-truth sebagai candidate            | 3.366 / 3.366 (100%) |
| Edge MATCH terverifikasi device sama      |       3.366 |
| Edge MATCH tidak terverifikasi            |          35 |
| Entity mencampur dua device ID            |            0 |
| Smoke test                                |     23 / 23 |

### Distribusi skor dan konsekuensi threshold

| Rentang probabilitas | Jumlah pasangan |
| -------------------- | --------------: |
| ≤ 1e-10              |         261.530 |
| 1e-10 – 0,001        |          46.336 |
| 0,001 – 0,01         |              25 |
| 0,01 – 0,1           |               2 |
| **0,1 – 0,9**        |        **0**    |
| ≥ 0,9                |           3.401 |

Distributinya bimodal: tidak ada satu pun pasangan pada rentang 0,1–0,9. Karena itu `REVIEW_THRESHOLD` mana pun di rentang (1e-10, 0,01] menghasilkan partisi keputusan yang identis — angka ini tidak perlu di-tuning, dan `0.001` yang sekarang dipakai bukan pilihan diskriminating.

Sebelum `REVIEW_THRESHOLD` diubah dari `1e-10` ke `0.001`, band REVIEW berisi 46.336 pasangan yang hampir seluruhnya bernilai ~0 sehingga membanjiri antrean tanpa menambah nilai review. Itu sebabnya review rate turun dari 14,77% ke 0,0087% **tanpa perubahan jumlah MATCH**.

Angka di atas merupakan hasil eksperimen pada lingkungan pengembangan dan tidak boleh dianggap sebagai estimasi performa pada dataset pelanggan lain.

### Evaluasi empat lapis

| Lapisan      | Fokus                                                           | Hasil                                                                     |
| ------------ | --------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **Blocking** | Apakah pasangan benar tersedia sebagai candidate?              | 3.366 / 3.366; coverage 100% pada pasangan referensi yang diuji.         |
| **Linkage**  | Keputusan model terhadap pasangan kandidat.                    | 3.366 edge terverifikasi, 0 false merge, 35 edge tanpa device truth.      |
| **Decision** | Distribusi keputusan berdasarkan threshold.                      | 1,09% auto-match, 0,0087% review, 98,90% non-match.                      |
| **Entity**   | Konsistensi hasil pengelompokan.                                | 3.366 pasangan referensi tergabung; 0 entity mencampur device ID.         |

---

## 10. Kualitas Label dan Feedback

Bagian ini penting karena **metrik pada dataset ini sangat bergantung pada kualitas label**.

### Kondisi saat ini

| Sumber label            | Jumlah | Catatan                                                                     |
| ----------------------- | -----: | --------------------------------------------------------------------------- |
| `data/labels/gold_labels.csv` | 245 pasangan | 17 `match`, 228 `no_match`                                     |
| `data/labels/feedback.csv`    | 342 keputusan | 114 `match`, 228 `no_match`                                   |
| `data/labels/review_queue.csv`| 150 baris   | **148 belum dilabeli**                                        |

### Temuan audit label

Cross-check label manusia terhadap `device_id` pada 342 keputusan:

| Keputusan manusia | device sama | device beda | tanpa device truth |
| ----------------- | ----------: | ----------: | -----------------: |
| `match` (114)     |         100 |           **8** |                6 |
| `no_match` (228)  |           0 |         228 |                 0 |

Kedelapan pasangan yang bertentangan seluruhnya berasal dari stratum `unlabelled_same_email`: **nama dan email identik, tetapi `customer_id`, `device_id`, tanggal lahir, nomor telepon, alamat, kota, dan provinsi semuanya berbeda.** Pasangan serupa yang benar-benar duplikat (kelompok pembanding) memiliki `customer_id` identik dan semua field identik.

Kesimpulan audit: **email identik + nama identik bukan bukti cukup untuk menyamakan customer.** Aturan pengaman di `apply_gold.py` sudah menolak penggabungan dengan konflik device, tetapi sinyal tersebut belum ditampilkan di halaman review, sehingga reviewer tidak melihatnya saat memutuskan.

Konsekuensi terhadap metrik: pada `outputs/threshold_evaluation_gold.json`, precision 1,0 dan recall 0,5294 (tp 9, fp 0, fn 8, tn 228). Angka recall tersebut dipengaruhi 8 label positif yang bertentangan dengan data sumber dan **tidak boleh dipakai sebagai dasar keputusan** sebelum label diperbaiki.

### Stratified gold set bukan sampel acak

Gold label disusun per stratum, bukan diambil acak. Setelah 8 label bertentangan dikoreksi, gold set menjadi trivially separable (seluruh positif berada pada P = 1,0), sehingga **tidak ada lagi kasus sulit di dalam gold set**. Gold set tidak dapat dipakai untuk menentukan threshold; hanya `threshold_eval` dan device-truth evaluation yang memberi informasi.

---

## 11. Model Lifecycle dan Feedback

```text
models/
├── v20261001_141528/
│   ├── model.json
│   ├── metadata.json
│   ├── thresholds.json
│   └── evaluation.json
└── latest.json
```

| File              | Isi                                                       |
| ----------------- | --------------------------------------------------------- |
| `model.json`      | Parameter Splink termasuk m/u per level.                  |
| `metadata.json`   | Jumlah record latih, seed, versi library, runtime.         |
| `thresholds.json` | Kebijakan threshold beserta siapa dan kapan 적용.         |
| `evaluation.json` | Ringkasan jumlah dan distribusi keputusan run tersebut.    |
| `latest.json`     | Pointer ke versi model aktif.                              |

Kebijakan: data baru memakai model tersimpan; training ulang adalah tindakan eksplisit; setiap versi menyimpan metadata dan evaluasi; perubahan threshold dicatat terpisah dari perubahan parameter model.

---

## 12. Incremental Deduplication

* Pemrosesan incremental sekitar 5 detik untuk batch berisi 100 baris.
* Pemrosesan penuh 216,62 detik pada run `v20261005_145258` (training baru).
* Tidak ditemukan perubahan entity ID lama ketika batch baru ditambahkan pada eksperimen tersebut.

Registry `data/processed/batch_registry.json` memiliki 9 batch dengan rentang `record_id` berurutan dan SHA-256 per file.

---

## 13. Batasan dan Interpretasi Hasil

### 13.1 `device_id` adalah referensi, bukan kebenaran mutlak

Pada dataset pengembangan, device ID membentuk grup `customer_id` 1:1. Artinya device ID **mewarisi semua bias source system** dan tidak menguji apa pun yang tidak tercermin di sana.

Batas yang terukur: **450 alamat email dipakai oleh lebih dari satu device ID**, dan pola dominannya adalah varian titik pada local part (`zulfa.narpati43@…` vs `zulfanarpati43@…`). Karena itu email identik tidak dapat dipakai sebagai bukti identitas tanpa dukungan field lain.

Kesesuaian terhadap device-truth menunjukkan konsistensi terhadap referensi yang tersedia, bukan jaminan model menemukan seluruh duplikat di data nyata.

### 13.2 Cakupan device truth tidak penuh

`COLUMN_MAP` hanya memetakan `device_ids` → `device_id(s)`. Batch `batch_0005` memakai nama kolom `device_id`, sehingga **200 record tidak memiliki device truth** dan 35 edge MATCH menjadi tidak terverifikasi. Coverage device truth perlu dibaca sebagai **3.366 dari 3.535 record yang punya device**, bukan 100% dari seluruh dataset.

### 13.3 Kualitas nomor telepon

Normalisasi telepon membuang ekstensi (`xNNN`) sebelum membuat kunci. Pengaruhnya terhadap hasil **nol** pada dataset ini (A/B: tidak ada pasangan dengan main-number identik tetapi ekstensi berbeda), jadi perbaikannya bersifat *latent correctness*, bukan peningkatan performa terukur.

Selain itu **2.115 dari 51.552 nomor telepon (4,10%) menjadi kurang dari 7 digit**, dan 1.855 di antaranya tepat 4 digit (contoh nilai mentah `-8296`). Aturan blocking `phone_prefix` memakai 7 digit, sehingga record ini tidak pernah menghasilkan prefix yang valid. Angka ini belum diperlakukan sebagai sinyal ketidakandalan pada perbandingan.

### 13.4 Keterbatasan gold label

Gold set berisi 245 pasangan dengan hanya 17 positif, disusun per stratum. Lihat bagian 10 untuk hasil audit label terhadap device truth. Ukuran ini tidak cukup untuk mengeneralisasi ke berbagai kondisi data.

### 13.5 Silver label bukan ground truth independen

F1 sebesar 1,0 pada evaluasi silver tidak menunjukkan performa sempurna. Silver label dibangun dari heuristik yang berkaitan dengan proses evaluasi, sehingga mengukur kesesuaian model terhadap aturan pembentukan label.

### 13.6 Asumsi dan parameter

| Parameter                    | Nilai | Status                                                       |
| ---------------------------- | ----- | ------------------------------------------------------------ |
| `M_ELSE_LEVEL_FLOOR`         | 0.05  | Asumsi, belum divalidasi.                                     |
| `LAMBDA_RECALL_ASSUMPTION`   | 0.7   | Asumsi, belum divalidasi.                                     |
| `MATCH_THRESHOLD`            | 0.9   | Tidak sensitif: tidak ada pasangan pada 0,1–0,9.             |
| `REVIEW_THRESHOLD`           | 0.001 | Tidak sensitif pada rentang (1e-10, 0,01].                    |

Parameter m/u model dipelajari melalui EM dan **belum pernah dibandingkan dengan tingkat kesepakatan yang terukur pada 342 label manusia**. Audit tersebut adalah pekerjaan berikutnya yang paling bernilai.

### 13.7 Pengujian typo bersifat sintetis

Recovery 200 dari 200 pasangan merupakan pengujian terhadap data sintetis yang dimodifikasi di dalam memori. Berguna untuk menguji perilaku pipeline pada skenario yang dirancang, bukan bukti tingkat keberhasilan pada data pelanggan nyata.

### 13.8 Keterbatasan skalabilitas

Benchmark yang terdokumentasi belum melampaui sekitar 51.500 baris. Kemampuan menangani jutaan record, performa pada distribusi data berbeda, serta kebutuhan infrastruktur untuk skala lebih besar masih perlu diuji terpisah.

---

## 14. Pengembangan Selanjutnya

**Kualitas label dan evaluasi**

* Perbaiki 8 gold label yang bertentangan dengan device truth, dengan backup dan alasan tercatat.
* Audit label berkala: cross-check keputusan manusia vs device truth per stratum.
* Bandingkan m/u model dengan tingkat kesepakatan terukur dari 342 label manusia.
* Perluas `COLUMN_MAP` agar `device_id` (tunggal) ikut terpetakan, lalu ukur ulang coverage device truth.
* Tandai nomor telepon < 7 digit sebagai tidakandal dan keluarkan dari blocking `phone_prefix`.

**Antarmuka**

* Tampilkan ringkasan kesepakatan field dan badge konflik device di halaman review — akar penyebab 8 mislabel.
* Tulis ulang `how_to_read()`: saat ini menjanjikan band "sekitar 50%" yang tidak pernah muncul pada data ini.
* Tampilkan diff pemetaan skema di halaman Upload agar kolom tak terpetakan terlihat.
* Perluas review queue; 27 pasangan pada band REVIEW adalah pekerjaan manual paling bernilai yang tersedia.

**Model dan skala**

* Menguji gold set dua kelas yang cukup representatif untuk menentukan threshold.
* Menguji skenario konflik informasi, missing value, dan duplikasi lintas sumber.
* Memperluas benchmark performa pada ukuran data yang lebih besar.

---

## 15. Status Proyek

**Status: Prototype Internal Demonstration Tool**

Sistem memiliki pipeline record linkage, mekanisme review, pembentukan entity, master record, evaluasi, model versioning, dan pemrosesan incremental yang berjalan terintegrasi pada dataset pengembangan.

Kualitas generalisasi model, keandalan pada data pelanggan yang lebih beragam, dan skalabilitas pada volume yang jauh lebih besar masih memerlukan validasi lebih lanjut. Hasilnya belum dapat dianggap sebagai jaminan kesiapan produksi.