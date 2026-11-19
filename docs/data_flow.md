# Data Flow — From Raw Input to Master Entity Table

## End-to-End Pipeline Diagram

```
data/raw/<batch_NNNN>.csv (artefak lokal; tidak masuk GitHub)
          │
          ▼
[Ingestion] ──► CSV parse ──► raw records (50K/108K)
          │
          ▼
[Standardization] ──► column mapping ──►
│                 │
│                 ▼
│       Raw → Std columns:
│       │           │
│       │           ├─ first_name_std
│       │           ├─ last_name_std
│       │           ├─ email_std
│       │           ├─ phone_std (digits only)
│       │           ├─ dob_std (YYYY-MM-DD)
│       │           ├─ city_std
│       │           ├─ state_std
│       │           ├─ email_domain_pre4 (4 karakter pertama domain)
│       │           ├─ phone_pre7 (7 digit pertama)
│       │           ├─ phone_last4 (4 digit terakhir)
│       │           ├─ dob_year_std (4 digit tahun)
│       │           ├─ last_name_std_pre3 (3 karakter pertama)
│       │           └─ first_name_std_pre3 (3 karakter pertama)
│                 │
                 ▼
          │
          ▼
[Blocking] ──► 12 blocking rules ──► union 86.699 kandidat pada
          │                       eksperimen 40k (blocking_benchmark.csv);
          │                       angka penuh bergantung data yang diproses
          │
          ▼
[EM Training] ──► m-prob & u-prob estimation ──►
          │           (5-8 iterations, blocked pair space)
          ▼
[Prediction] ──► match_probability per pair ──►
          │           decision: MATCH / REVIEW / NON_MATCH
          │           business_rule: strong_agreement_email_name_address,
          │                          unverified_dob, no_field_agreement,
          │                          conflicting_email_fullname
          ▼
[Thresholding] ──► MATCH_THRESHOLD (0.84) ──►
          │           REVIEW_THRESHOLD (0.35)
          │           hasil terukur ada di outputs/evaluation_report.json,
          │           bukan angka tetap di dokumen ini
          ▼
[Outputs] ──► splink_predictions.parquet
          │           master_customers.parquet
          │           entity_map.parquet
          │           evaluation_report.json
          │           training logs
          ▼
[Human Review] ──► review_queue.csv ──► feedback → model retrain
```

## Key Intermediate Artifacts

| Artifact | Path | Description |
|---|---|---|
| `crm_standardized.parquet` | `data/processed/` | artefak lokal; jumlah record bergantung batch yang diproses |
| `splink_predictions.parquet` | `outputs/` | Pair-level: match_probability, decision, business_rule, pair_id |
| `splink_predictions_sample.parquet` | `outputs/` | 10K-row sample for inspection |
| `entity_map.parquet` | `outputs/` | Mapped record_ids → entity_id (resolved entities) |
| `master_customers.parquet` | `outputs/` | Deduplicated customer table (one row per entity) |
| `gold_labels.csv` | `data/labels/` | 3.890 pasangan berlabel (1.372 `match`, 2.518 `no_match`) |
| `thresholds_override.json` | `outputs/` | Opsional; default `MATCH=0.84`, `REVIEW=0.35` ada di `src/config.py` |

## Data Integrity Rules (per AGENTS.md)

1. **Preserve raw values**: Never overwrite `first_name` with `first_name_std`. Keep both.
   - `first_name` = original source value
   - `first_name_std` = standardized (lowercase, cleaned) value

2. **Source customer_id ≠ entity_id**: 
   - `record_id` = physical record identifier (generated during preprocessing)
   - `customer_id` = source-system identifier (from raw CSV)
   - `entity_id` = resolved real-world entity (from Splink linkage)
   - Do NOT treat source `customer_id` as ground truth

3. **Standardization first**: Do NOT run linkage on raw unstandardized data.
   - Pipeline order: ingestion → schema validation → record_id → **standardization** → feature engineering → blocking → linkage

4. **Never silently delete records**: If filtering is needed, create a new column (e.g., `is_duplicate_flag`) rather than dropping rows.

5. **Typed columns only**: Comparison levels operate on `_std` columns only. Raw columns are not used in m-probability estimation.

## Field Standardization Details

| Field | Transformations |
|---|---|
| `first_name` → `first_name_std` | `lower()`, strip leading/trailing whitespace, remove non-alphabetic characters (keep hyphens, apostrophes), collapse internal whitespace |
| `last_name` → `last_name_std` | Same as first_name |
| `email` → `email_std` | `lower()`, strip whitespace, validate `@` present, remove trailing dots |
| `phone_number` → `phone_std` | Ambil digit saja; buang ekstensi `xNNN`; buang prefix internasional `00` lalu satu `0` domestik di depan |
| `dob` → `dob_std` | Parse to `datetime`, format as `YYYY-MM-DD`, handle `None`/empty → `NULL` |
| `city` → `city_std` | `lower()`, strip whitespace |
| `state` → `state_std` | `upper()`, 2-letter country code (US states only in this dataset) |
| `email_domain_pre4` | Extracted from `email_std`: split at `@`, take first 4 chars of domain (e.g., `gmail.com` → `gmai`, `yahoo.com` → `yaho`) |
| `phone_pre7` | First 7 digits of `phone_std` (e.g., `6277945711` → `6277945`) |
| `phone_last4` | Last 4 digits of `phone_std` (e.g., `6277945711` → `5711`) |
| `dob_year_std` | First 4 characters of `dob_std` (tahun lahir) |
| `last_name_std_pre3` | First 3 characters of `last_name_std` (e.g., `saunders` → `sau`, `smith` → `smi`) |
| `first_name_std_pre3` | First 3 characters of `first_name_std` (e.g., `john` → `joh`, `ali` → `ali`) |
| `phonetic_last_name`, `phonetic_first_name` | Soundex dari nama terstandardisasi; dipakai level perbandingan nama |