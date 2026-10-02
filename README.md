# CRM Entity Resolution / Deduplication — Splink + DuckDB

Sistem pendeteksi dan penggabung duplikat record customer (Entity Resolution /
Deduplication) berbasis probabilistic linkage. Dibangun dengan **Python +
Splink + DuckDB**, antarmuka **Streamlit**.

Record A: `John Smith / john.smith@gmail.com / 08123456789`
Record B: `Jhon Smith / john.smith@gmail.com / +628123456789`

Keduanya mungkin orang yang sama walau nilainya tidak identik. Sistem ini
memutuskan secara probabilitas — bukan hanya kecocokan persis — lalu
menggabungkannya menjadi satu `entity_id`.

> Dataset development: `crm_50000_customers_dirty_v3.csv` (Kaggle Customer 360).
> 50k adalah dataset **development/evaluasi**, bukan klaim kapasitas produksi.

---

## 1. Arsitektur Ringkas

```
CSV masuk
  → validasi skema (kolom wajib + kolom blocking)
  → record_id generation (per batch, dari registry)
  → standardisasi (kolom *_std; nilai asli TIDAK pernah ditimpa)
  → blocking (12 aturan → pasangan kandidat; tanpa ini semua-pasangan = O(n²))
  → Splink (Fellegi-Sunter, EM training → skor per pasangan)
  → keputusan: MATCH / REVIEW / NON_MATCH
  → clustering (union-find atas MATCH → entity_id)
  → master record (satu baris per entity + lineage)
  → evaluasi 4 lapis + feedback manusia (gold label)
```

Tiga konsep yang tidak boleh disamakan:

| Istilah | Arti |
|---|---|
| `record_id` | identifier satu baris fisik (dibuat sistem) |
| `customer_id` | identifier dari source system (bukan kebenaran) |
| `entity_id` | hasil resolusi — orang nyata di dunia |

---

## 2. Prasyarat

- Python 3.10+ (dikembangkan di 3.14)
- Windows / Linux / macOS (perintah contoh memakai PowerShell)
- Tidak perlu Spark, tidak perlu server database — DuckDB berjalan di dalam proses

Instalasi:

```powershell
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

Dependensi utama: `pandas`, `pyarrow`, `splink==4.0.17`, `streamlit`.

---

## 3. Quick Start

```powershell
# 1. Jalankan seluruh pipeline (train model baru + evaluasi), ±205 detik
python -m src.run_all

# 2. Pakai model tersimpan (tanpa retrain), ±90 detik
python -m src.run_all --reuse-model latest

# 3. Cek invarian (20 pemeriksaan)
python tests/test_smoke.py

# 4. Buka aplikasi web
.venv/Scripts/streamlit run app.py --server.address 0.0.0.0
```

> Retrain tidak dijalankan otomatis hanya karena file baru masuk
> (MASTER_CONTEXT §15). `--reuse-model latest` adalah jalur default untuk
> data baru; retrain adalah aksi eksplisit di halaman Retrain.

---

## 4. Struktur Direktori

```
src/                 modul pipeline (satu file satu tanggung jawab)
  config.py          path, COLUMN_MAP, 12 blocking rules, threshold
  standardize.py     normalisasi *_std, blocking key, deteksi urutan tanggal
  splink_model.py    training Splink + scoring + keputusan 3 arah
  clustering.py      union-find MATCH → entity_id
  labels.py          silver label, antrean review, promote gold
  apply_gold.py      terapkan label manusia ke keputusan (dengan guard)
  close_gold_loop.py satu perintah: promote → feedback → apply → evaluate
  entity_correction.py  split/merge entity manual + audit log
  evaluate.py        evaluasi 4 lapis (blocking/linkage/decision/entity)
  scenario_eval.py   skenario kasus nyata (typo, email sama, blocking miss)
  incremental.py     hubungkan batch baru tanpa re-run penuh
  run_all.py         orkestrasi seluruh langkah
app.py               halaman upload Streamlit
pages/               9 halaman Streamlit (review, master, dashboard, dst.)
data/raw/            CSV mentah per batch (di-gitignore, tidak ikut push)
data/processed/      hasil standardisasi parquet (di-gitignore)
data/labels/         antrean review + gold label (di-gitignore)
outputs/             prediksi, entity map, laporan evaluasi (di-gitignore)
models/              versi model JSON (config/parameter saja — ikut push)
tests/test_smoke.py  20 invariant check
notebooks/           skrip demo & profiling
docs/, *.md          PRD, DESIGN, AGENTS, MASTER_CONTEXT
```

Aturan data: **file `*.csv` / `*.parquet` tidak pernah ikut ke git**
(diatur `.gitignore` termasuk jaring pengaman global). Yang di-push hanya kode,
dokumentasi, dan parameter model.

---

## 5. Perintah Lengkap

Pipeline (urutan `run_all`):

| Langkah | Perintah | Output |
|---|---|---|
| 1. Profiling | `python -m src.profiling` | `outputs/profiling_summary.json` |
| 2. Standardisasi | `python -m src.standardize` | `data/processed/crm_standardized.parquet` |
| 3. Silver label | `python -m src.labels --silver-only` | `data/labels/silver_pairs.csv` |
| 4. Blocking benchmark | `python -m src.blocking_benchmark --full` | `outputs/blocking_benchmark.csv` |
| 5. Splink model | `python -m src.splink_model --full` | `outputs/splink_predictions.parquet` |
| 6. Antrean review | `python -m src.labels --full` | `data/labels/review_queue.csv` |
| 7. Clustering | `python -m src.clustering --full` | `outputs/entity_map.parquet` |
| 8. Master record | `python -m src.master_record` | `outputs/master_customers.parquet` |
| 9. Evaluasi | `python -m src.evaluate` | `outputs/evaluation_report.json` |

Perintah pendukung:

```powershell
python -m src.threshold_eval --full        # precision/recall/F1 per threshold
python -m src.scenario_eval                # skenario kasus nyata
python -m src.labels --promote             # antrean review → gold (backup otomatis)
python -m src.close_gold_loop --all        # promote + apply + evaluasi sekali jalan
python -m src.apply_gold                   # terapkan gold ke keputusan (dry-run)
python -m src.model_lifecycle              # daftar versi model
python -m src.review_sample --band match   # sampel pasangan untuk review
python -m src.stress_test --pairs 200      # pemulihan pada duplikat rusak (typo)
python -m src.batch_eval                   # stabilitas entity antar batch
python -m src.registry                     # daftar batch & kepemilikan record_id
python -m src.validate_upload file.csv     # cek skema sebelum registrasi
python -m src.incremental                  # link batch baru (tanpa re-run penuh)
python -m src.entity_correction --history  # riwayat split/merge entity
```

---

## 6. Demo Streamlit (9 halaman)

```powershell
.venv/Scripts/streamlit run app.py --server.address 0.0.0.0
```

| Halaman | Fungsi |
|---|---|
| `app.py` (Upload) | upload CSV → validasi → registrasi batch → pipeline |
| `1_review` | antrean review: label `match` / `no_match` → promote gold |
| `2_master` | telusuri master record, koreksi nilai, tandai salah gabung |
| `3_dashboard` | metrik: auto-match/review rate, distribusi skor, batch per minggu |
| `4_retrain` | status model, perbandingan A/B, rollback, threshold exploration |
| `5_queue` | cakupan band REVIEW vs antrean yang sudah disampel |
| `6_batch` | review proposal batch baru sebelum digabung (apply / reject) |
| `7_gaps` | singleton entity & REVIEW yang belum masuk antrean |
| `8_explain` | bukti field-level per pasangan (bobot m/u, gamma) |
| `9_history` | riwayat keputusan per pasangan/record + audit koreksi entity |

Alur upload: CSV divalidasi (kolom wajib + kolom blocking, delimiter/encoding
dideteksi, format tanggal ditanya jika ambigu) → hanya disimpan saat tombol
registrasi ditekan (sha256 menolak file ganda) → batch baru di-stage lalu
diverifikasi manusia di halaman Batch review sebelum digabung.

---

## 7. Hasil Terukur

Dari run terakhir (`51.555` baris = 9 batch, model `v20261001_141528`):

```
pasangan kandidat (union 12 aturan blocking)   311.294
keputusan   MATCH 3.401 | REVIEW 45.963 | NON_MATCH 261.930
auto-match rate 1,09% | review rate 14,77% | non-match rate 84,14%
entity hasil clustering                         48.380
device-truth dalam satu entity        3.366 / 3.366 = 100%
entity mencampur 2 device id                     0
salah gabung lintas batch                         0
entity_id lama berubah saat batch baru masuk      0
recovery pada 200 duplikat ber-typo (sintetis)  200/200
smoke test                                  20/20 PASS
```

Evaluasi dilaporkan dalam **4 lapis terpisah** (DESIGN §17) — tidak pernah
dijadikan satu angka:

| Lapis | Pertanyaan | Terukur |
|---|---|---|
| blocking | apakah pasangan benar sempat jadi kandidat? | 3.366/3.366 (ceiling 1.0) |
| linkage | apakah model menilainya benar? | 3.366 di atas threshold · 0 false merge |
| decision | apakah threshold menghasilkan split wajar? | 1,09% auto-match · 14,77% review |
| entity | apakah record satu orang berakhir di satu entity? | 3.366 bersama · 0 terpecah |

---

## 8. Model Lifecycle

```
models/v20261001_141528/
    model.json        parameter Splink terlatih (m/u per level)
    metadata.json     data latih, seed, versi library, runtime
    thresholds.json   policy keputusan yang dipakai menilainya
    evaluation.json   jumlah/rate keputusan dari run itu
models/latest.json    pointer versi aktif (dipakai rollback)
```

Threshold disimpan **bersama** model: skor yang direview di bawah threshold
berbeda diam-diam mengubah arti MATCH. Rollback = ganti `latest.json`
(halaman Retrain). Feedback manusia `feedback.csv` append-only, terkunci
`(pair_id, model_version)` — bahan keputusan kapan retrain dibutuhkan.

---

## 9. Batasan yang Diketahui (baca sebelum mempercayai angka)

1. **`device_id` adalah kunci jawaban, bukan bukti independen.** Data 50k ini
   degeneratif: 48.200 device id = 48.200 grup `customer_id`, tidak ada grup
   membawa 2 device. Kesepakatan dengannya hanya membuktikan pipeline
   mereproduksi pengelompokan sumber — bukan apa pun tentang fuzzy duplicate
   atau dataset lain.
2. **`MATCH_THRESHOLD = 0.9` / `REVIEW_THRESHOLD = 1e-10` belum divalidasi
   gold set dua kelas.** Reukur ulang saat data/comparison/floor berubah.
   Gold saat ini: 242 pasangan (14 match / 228 no_match) — precision terukur
   1.0, recall 0,43; 8 pasangan positif sengaja **tidak** dipaksa merge karena
   konflik device id (guard di `apply_gold.py`).
3. **`F1 = 1.0` pada silver itu artefak**, bukan capaian — silver dibuat dari
   heuristik yang sama dengan yang dievaluasi.
4. **`M_ELSE_LEVEL_FLOOR = 0.05` dan `LAMBDA_RECALL_ASSUMPTION = 0.7` adalah
   asumsi**, bukan hasil ukur di data kotor nyata.
5. **Recovery typo 100% itu sintetis** (`stress_test` merusak record di memori)
   — bukan klaim kemampuan typo pada data client.
6. **Angka berubah saat retrain** — itu sebabnya upload memakai model terakhir
   secara default; retrain aksi manual.
7. **Skalabilitas**: blocking sudah dibenchmark (kandidat, coverage, runtime);
   incremental terukur (±5 dtk per batch 100 baris vs ±90 dtk full run);
   **belum** diuji di atas ~51,5 ribu baris.

---

## 10. Referensi Dokumen Lain

| Dokumen | Isi |
|---|---|
| `PRD.md` | requirement fungsional FR-01..FR-15, status PoC |
| `DESIGN.md` | arsitektur berlapis, strategi backend, evaluasi 4 lapis |
| `MASTER_CONTEXT.md.txt` | konsep identitas, siklus model, aturan scaling |
| `AGENTS.md` | aturan kontribusi/kerja untuk AI agent & manusia |
| `docs/AGENT_USAGE.md` | peta modul & disiplin scope |
