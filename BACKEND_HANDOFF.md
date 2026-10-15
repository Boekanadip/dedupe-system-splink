# Backend Handoff — CRM Entity Resolution

Untuk backend engineer. Bagian 1 = metrik yang perlu dimonitor. Bagian 2 = interface contract.

Posisi: ini sistem **data science** (Splink + DuckDB). Belum ada API, scheduler, auth, atau CDC.
Backend engineer yang membangun lapisan itu di atas interface ini.

---

## 1. Metrik yang Dimonitor

Sumber: file yang sudah ditulis pipeline hari ini. Backend tinggal scrape, tidak perlu hitung ulang.

### 1.1 Pipeline health (per run)

| Metrik | Sumber | Key | Tipe | Alert |
|---|---|---|---|---|
| Status run | `outputs/run_summary.json` | `scope`, `total_seconds`, `model_version` | timing | `total_seconds` > 2× median 10 run terakhir |
| Status job DB | `outputs/job_run_summary.json` | `status`, `exit_code`, `total_seconds` | enum | `status != "succeeded"` atau `exit_code != 0` |
| Pipeline lock | `outputs/.pipeline_running` | `pid`, `started_at`, `note` | liveness | lock hidup > 7200s (stale) — `config.pipeline_locked()` sudah deteksi ini |
| Retrain lock | `outputs/.retraining` | PID | liveness | PID mati tapi lock ada |
| Runtime per step | `outputs/run_summary.json` | `steps[].seconds` | timing | step mana pun > `--step-timeout` (default 1800s) |

### 1.2 Data quality (per upload/ingest)

| Metrik | Sumber | Key | Tipe | Alert |
|---|---|---|---|---|
| Validasi skema | `outputs/upload_validation_report.json` | `status`, `blocking[]`, `warnings[]` | enum | `status == "rejected"` |
| Kolom blocking hilang | idem | `blocking[]` | list | ada isi → batch ditolak |
| Null rate kolom kunci | idem | `null_profile.<col>.null_pct` | rate | `first_name`/`last_name` > 5%; `email`+`phone` null semua → unlinkable |
| Duplikat exact dalam batch | idem | `exact_duplicate_rows` | count | > 0 (perlu review, bukan auto-hapus) |
| Urutan tanggal ambigu | idem | `date_formats.dob.needs_answer` | bool | `true` → batch gagal standardize |

### 1.3 Output model (per run / per batch)

| Metrik | Sumber | Key | Tipe | Alert |
|---|---|---|---|---|
| Distribusi keputusan | `outputs/evaluation_report.json` | `decision.counts.{MATCH,REVIEW,NON_MATCH}` | count | REVIEW > 10.000 → antrean numpuk |
| Rate keputusan | idem | `decision.rates.{auto_match_rate,review_rate,non_match_rate}` | rate | auto_match_rate > 5% → investigasi (0,86% baseline) |
| Jumlah pasangan kandidat | idem | `blocking.candidate_pairs` | count | > 2× baseline → blocking bocor |
| Recall ceiling blocking | idem | `blocking.blocking_recall_ceiling` | rate | < 0,99 → aturan blocking kehilangan kandidat |
| Ukuran antrean review | `data/labels/review_queue.csv` | `review_status == "pending"` | count | > 500 pending → reviewer kewalahan (baseline 295) |
| Pasangan per review | idem | jumlah baris `pending` / reviewer aktif | rate | > 50/reviewer/hari |

### 1.4 Entity stability (per run)

| Metrik | Sumber | Key | Tipe | Alert |
|---|---|---|---|---|
| Jumlah record → entity | `outputs/evaluation_report.json` | `entity.{records,entities,records_merged_away}` | count | `records_merged_away` > 5% records → over-merge |
| Entity terbesar | idem | `entity.largest_entity` | count | > 100 → satu entity menampung terlalu banyak (kemungkinan false merge) |
| Distribusi ukuran cluster | idem | `entity.cluster_size_distribution` | dist | muncul cluster size > 6 → investigasi |
| Split cross-entity | idem | `entity.truth_pairs_split_across_entities` | count | > 0 → recall rusak |
| Merge cross-device | idem | `entity.entities_mixing_two_device_ids` | count | > 0 → false merge (device = proxy 1 orang) |
| Churn entity_id | `outputs/batch_linkage_report.json` | `old_entity_ids_changed` | count | > 0 → downstream yang simpan entity_id akan putus (temuan #1) |

### 1.5 DB ingestion (per job)

| Metrik | Sumber | Key | Tipe | Alert |
|---|---|---|---|---|
| Rows fetched | `outputs/job_run_summary.json` | `rows` | count | 0 berturut-turut → watermark macet |
| Watermark position | `data/processed/db_watermark.json` | `<source>::<table>.updated_at` | snapshot | umur watermark > 24h → pipeline tidak jalan |
| Insert vs update | `outputs/db_refresh_report.json` | `new_rows`, `update_rows` | count | update >> insert wajar; insert >> 0 terus-terusan → key map bocor |
| Stale entity | `outputs/db_stale_entities.json` | panjang array | count | > 0 → perlu review manual, belum di-resolve |
| Key map size | `outputs/db_refresh_report.json` | `key_map_size` | count | tidak tumbuh saat insert → sync gagal |

### 1.6 Evaluasi model (per gold update)

| Metrik | Sumber | Key | Tipe | Alert |
|---|---|---|---|---|
| Precision @ 0.9 | `outputs/threshold_evaluation_gold.json` | `results[threshold=0.9].precision` | rate | < 0,95 → false merge naik |
| Recall @ 0.9 | idem | `results[threshold=0.9].recall` | rate | < 0,95 → duplikat lolos |
| Jumlah gold | idem | `positives + negatives` | count | tidak tumbuh → tidak ada review baru masuk |
| Skor positif terendah | tests `review_floor_drops_no_gold_positive` | `min(match_probability)` gold positive | rate | turun di bawah `REVIEW_THRESHOLD` → floor terlalu tinggi |

### 1.7 Apa yang SUDAH tersedia untuk monitoring

`src/health.py` — CLI read-only yang output JSON standar:
```bash
python -m src.health          # JSON ke stdout
python -m src.health --pretty # JSON terformat
```

Output berisi: `status` (healthy/degraded/critical), `alerts[]` (level + message), dan 7 section: `pipeline`, `data_quality`, `model_output`, `entity`, `db_ingestion`, `evaluation`, `decision_distribution`.

Threshold alert ada di `alert_config` dalam output. Backend tinggal:
- `GET /health` → `python -m src.health` → return JSON
- `GET /metrics` → parse JSON, push ke Prometheus/DB
- Alerting → check `alerts[]` atau `status != "healthy"`

### 1.8 Apa yang BELUM ada (perlu backend bangun)

- **Tidak ada time-series storage.** `incremental_history.jsonl` satu-satunya append-only. Sisanya snapshot per run. Backend perlu scrape ke DB/Prometheus setiap run selesai.
- **Tidak ada alerting.** Semua threshold di atas belum diimplementasikan di mana pun.
- **Tidak ada `run_id` linking.** `evaluation_report.json` dan `run_summary.json` tidak saling terhubung. Korelasi pakai `model_version` + mtime.
- **Report ditulis tanpa atomic** di beberapa tempat (`stage0_audit`, `eval_truth`, `batch_eval`, `label_audit`, `threshold_eval`). Monitor harus toleran JSON terpotong saat crash.
- **`threshold_evaluation_gold.json` tanpa timestamp.** Pakai file mtime.

---

## 2. Interface Contract

### 2.1 Input schema

**Wajib** (`validate_upload.REQUIRED_COLUMNS`):
```
first_name, last_name
```

**Salah satu** (`ONE_OF`):
```
email  atau  phone_number
```

**Kolom blocking aktif** (diturunkan dari `BENCHMARK_RULES`, saat ini 8 kolom):
```
first_name, last_name, email, phone_number, address, city, state, dob
```

**Kolom optional** (meningkatkan recall, tidak memblocking):
```
country, customer_id, device_id(s), gender, signup_date, source
```

**Khusus DB** (untuk update-in-place):
```
customer_pk   (BIGINT/UUID — primary key sumber)
updated_at    (TIMESTAMP — watermark kolom)
```

**Nama kolom sumber berbeda dari pipeline?** Isi `DB_COLUMN_MAP` di `src/config.py`. Contoh:
```python
DB_COLUMN_MAP = {"first_nm": "first_name", "tgl_lahir": "dob"}
```

**Format file**: CSV (`;` atau `,`, auto-detect). Encoding: utf-8, utf-8-sig, atau latin-1.

### 2.2 Output artifacts

Semua path relatif terhadap project root.

| Artifact | Format | Kolom utama | Ditulis oleh |
|---|---|---|---|
| `data/processed/crm_standardized.parquet` | parquet | `record_id`, semua `*_std`, `customer_pk?` | `standardize`, `incremental`, `db_refresh` |
| `outputs/splink_predictions.parquet` | parquet | `record_id_l/r`, `match_probability`, `match_weight`, `decision`, `business_rule`, `gamma_gamma_*` | `splink_model`, `incremental` |
| `outputs/entity_map.parquet` | parquet | `record_id`, `entity_id` (`ent_XXXXXX`) | `clustering`, `incremental` |
| `outputs/master_customers.parquet` | parquet | `entity_id`, `record_count`, `master_*_std`, `conflicted_fields` | `master_record` |
| `data/labels/review_queue.csv` | CSV (30 kolom) | `record_id_l/r`, `stratum`, `match_probability`, `label`, `review_status` | `labels`, `review_sample`, `db_refresh` |
| `data/labels/gold_labels.csv` | CSV (10 kolom) | `record_id_l/r`, `label`, `stratum`, `match_probability` | `labels --promote` |

**Sidecar `.meta.json`** ada di setiap parquet. Berisi provenance:
`artifact`, `scope`, `model_version`, `match_threshold`, `review_threshold`, `runtime_seconds`, `trained`.
Backend baca ini untuk lineage, jangan parse parquet untuk dapat metadata.

### 2.3 Decision thresholds

| Konstanta | Nilai | Makna | Sumber |
|---|---|---|---|
| `MATCH_THRESHOLD` | 0.9 | `p >= 0.9` → auto-MERGE | `config.py` |
| `REVIEW_THRESHOLD` | 1e-8 | `1e-8 <= p < 0.9` → REVIEW | `config.py` |
| — | `p < 1e-8` | NON_MATCH | — |

Override: `outputs/thresholds_override.json` (`match_threshold`, `review_threshold`).
Pipeline membaca override ini otomatis saat import.

**Business rules** (menimpa keputusan model):
- `email+nama+alamat` sama + dob sama/selisih ≤ 366 hari → paksa **MATCH**
- `email+nama+alamat` sama + dob beda > 366 hari → paksa **REVIEW**
- Nol field identitas cocok → paksa **NON_MATCH**

### 2.4 CLI commands

Semua command dijalankan dari project root. Exit code: `0` = sukses, `1` = gagal/rejected.

**Full pipeline:**
```bash
python -m src.run_all --full                    # train + predict + cluster + evaluate
python -m src.run_all --sample                  # smoke test 10k rows
python -m src.run_all --full --reuse-model latest  # predict tanpa retrain
```

**Batch incremental:**
```bash
python -m src.incremental --batch batch_0018.csv --stage   # compute + staging
python -m src.incremental --apply                          # apply staged proposal
python -m src.incremental --reject                         # discard staged
```

**DB ingestion:**
```bash
python -m src.db_export --source <dsn> --table <tbl> --watermark   # fetch + register batch
python -m src.db_refresh --source <dsn> --table <tbl>              # update-in-place
python -m src.job_run --source <dsn> --table <tbl> --mode stage    # export + incremental
```

`--source` format: path `.duckdb` atau connection string (`postgres://user:pass@host/db`).

**Review workflow:**
```bash
python -m src.labels --promote       # review_queue.csv (sudah diisi) → gold_labels.csv
python -m src.labels --full          # rebuild queue dari full predictions
python -m src.review_sample --n 100 --band review    # sample band untuk review
```

**Validasi:**
```bash
python -m src.validate_upload data/raw/batch_0018.csv   # exit 1 jika rejected
```

**Monitoring/evaluasi:**
```bash
python -m src.evaluate              # evaluation_report.json (4 layer)
python -m src.threshold_eval --source gold   # threshold_evaluation_gold.json
python -m src.blocking_benchmark    # blocking_benchmark.csv
python -m src.stage0_audit          # stage0_audit.json
```

### 2.5 Locking protocol

Sebelum menjalankan pipeline command, backend **wajib** cek:
```python
from src.config import pipeline_locked
lock = pipeline_locked()   # None = aman; dict = sedang jalan
if lock:
    # tampilkan lock["note"], lock["pid"], umur lock
    # jangan jalankan command lain sampai lock lepas
```

Lock file: `outputs/.pipeline_running` = `{"pid": int, "started_at": float, "note": str}`.
Stale setelah 7200s (2 jam) — otomatis diabaikan.

Retrain lock: `outputs/.retraining` (berisi PID string). Ditulis oleh `pages/4_retrain.py`.

### 2.6 Config files

| File | Format | Dipakai oleh |
|---|---|---|
| `config/job.json` | `{"source", "table", "mode", "date_order", "watermark"}` | `job_run` |
| `config/blocking_rules.json` | `[{"name": "...", "columns": ["col1", ...]}, ...]` | `load_benchmark_rules()` |
| `outputs/thresholds_override.json` | `{"match_threshold", "review_threshold"}` | `config.py` (auto-load) |
| `data/processed/batch_registry.json` | `{"version", "next_start_index", "batches": [...]}` | `registry` |
| `data/processed/db_watermark.json` | `{"<source>::<table>": {"updated_at": "..."}}` | `db_source` |
| `data/processed/record_key_map.json` | `{"<customer_pk>": "<record_id>", ...}` | `db_refresh` |

`config/blocking_rules.json` **opsional**. Kalau tidak ada, pakai `DEFAULT_BENCHMARK_RULES` (12 aturan).
Kalau ada, **seluruh pipeline** (validasi, standardize, blocking, model) otomatis ikut aturan tersebut.

### 2.7 Environment variables

| Var | Default | Fungsi |
|---|---|---|
| `PIPELINE_STAGING` | (unset) | `1` = tulis ke `.staging/`, commit di akhir. Di-set otomatis oleh `run_all`. |
| `DB_SOURCE` | — | override `--source` untuk `job_run` |
| `DB_TABLE` | — | override `--table` untuk `job_run` |
| `JOB_MODE` | — | override `--mode` untuk `job_run` |
| `JOB_DATE_ORDER` | — | override `--date-order` untuk `job_run` |
| `PYTHONIOENCODING` | — | di-set `utf-8:replace` oleh `run_all` saat panggil subprocess |

### 2.8 Exit codes & error handling

| Kondisi | Perilaku |
|---|---|
| `validate_upload` rejected | exit 1, `blocking[]` berisi alasan |
| `standardize` gagal date-order | `SystemExit` dengan pesan "Cannot tell whether ... is d/m/Y or m/d/Y" |
| `standardize` kolom blocking hilang | `SystemExit` dengan daftar kolom hilang |
| `incremental` tanpa model | `SystemExit` "No saved model" |
| `db_refresh` tanpa `customer_pk` | `SystemExit` |
| `db_refresh` key map stale | `SystemExit` dengan daftar record_id hilang |
| Pipeline gagal di tengah | staging dibuang (`discard_staged`), state lama utuh |

**Jangan parse stderr untuk logic.** Baca exit code + file report. Stderr hanya untuk logging.

### 2.9 Apa yang perlu backend bangun (belum ada)

1. **HTTP API** — wrap CLI commands sebagai endpoints. Contoh:
   - `POST /ingest` → `db_export` + `incremental --stage`
   - `POST /ingest/{batch}/apply` → `incremental --apply`
   - `GET /status` → baca `job_run_summary.json` + `pipeline_locked()`
   - `GET /metrics` → scrape semua metrik di Bagian 1
   - `GET /review/queue` → baca `review_queue.csv`
   - `POST /review/{pair_id}` → tulis label + `labels --promote`
   - `GET /entities/{entity_id}` → baca `master_customers.parquet`

2. **Scheduler** — cron/Airflow untuk `job_run` periodik. Cek lock sebelum invoke.

3. **Auth** — Streamlit saat ini tanpa login. API perlu auth.

4. **Time-series DB** — scrape `evaluation_report.json`, `job_run_summary.json`, `incremental_history.jsonl` ke Postgres/Prometheus setiap run.

5. **Alerting** — implement threshold di Bagian 1.

6. **Multi-client** — saat ini satu konfigurasi global. Per-client = salin `config/blocking_rules.json` per client, atau tambah parameter `client_id` ke CLI.

### 2.10 Batasan yang harus dikomunikasikan ke stakeholder

- `entity_id` hanya stabil selama `batch_registry.json` tidak berubah. Registry berubah → ID bisa geser. Downstream yang menyimpan `entity_id` harus siap re-mapping via `record_id`.
- Gold labels **stratified by model behavior**, bukan sampel acak. Precision/recall dari gold tidak boleh diekstrapolasi ke seluruh populasi.
- Threshold (0.9 / 1e-8) dipilih dari evaluasi pada gold set saat ini. Kalau distribusi data berubah, ukur ulang sebelum ubah.
- `m_else_level_floor` untuk `dob_std` (0.001) adalah **asumsi**, belum diuji secara aislasi terhadap gold. Dampak terukur: 0 gold positive hilang di run saat ini, tapi belum ada A/B test.
- Sistem unsupervised — tidak ada train/test split klasik. Evaluasi pakai gold labels yang di-review manusia.
