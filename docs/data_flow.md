# Data Flow — From Raw Input to Master Entity Table

## End-to-End Pipeline Diagram

```
data/raw/crm_50000_customers_dirty_v.csv
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
│       │           ├─ email_domain_pre4
│       │           └─ phone_pre7 (last 7 digits)
│       │           ├─ last_name_std_pre3 (last 3 chars)
│       │           └─ first_name_std_pre3 (first 3 chars)
│                 │
                 ▼
          │
          ▼
[Blocking] ──► 11 blocking rules ──► candidate pairs (~1.5M from 5.8B)
          │                       (phone_prefix, email_domain_name,
          │                        name_prefix, city_dob, etc.)
          │
          ▼
[EM Training] ──► m-prob & u-prob estimation ──►
          │           (5-8 iterations, blocked pair space)
          ▼
[Prediction] ──► match_probability per pair ──►
          │           decision: MATCH / REVIEW / NON_MATCH
          │           forced rules: 9.1K MATCH, 702K NON_MATCH
          ▼
[Thresholding] ──► MATCH_THRESHOLD (0.84) ──►
          │           REVIEW_THRESHOLD (0.35)
          │           recall@0.84: 0.9976 / precision 0.9350 (target ≥0.95)
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
| `crm_standardized.parquet` | `data/processed/` | 108,427 records, all columns standardized |
| `splink_predictions.parquet` | `outputs/` | Pair-level: match_probability, decision, business_rule, pair_id |
| `splink_predictions_sample.parquet` | `outputs/` | 10K-row sample for inspection |
| `entity_map.parquet` | `outputs/` | Mapped record_ids → entity_id (resolved entities) |
| `master_customers.parquet` | `outputs/` | Deduplicated customer table (one row per entity) |
| `gold_labels.csv` | `data/labels/` | 3,593 labeled pairs (1,099 match, 2,494 non-match) |
| `thresholds_override.json` | `outputs/` | MATCH_THRESHOLD=0.84, REVIEW_THRESHOLD=0.35 |

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
| `phone_number` → `phone_std` | Keep digits only (`re.sub(r'\\D', '', value)`), format as plain digit string (e.g., `6277945711`), strip leading zeros if present |
| `dob` → `dob_std` | Parse to `datetime`, format as `YYYY-MM-DD`, handle `None`/empty → `NULL` |
| `city` → `city_std` | `lower()`, strip whitespace |
| `state` → `state_std` | `upper()`, 2-letter country code (US states only in this dataset) |
| `email_domain_pre4` | Extracted from `email_std`: split at `@`, take first 4 chars of domain (e.g., `gmail.com` → `gmai`, `yahoo.com` → `yaho`) |
| `phone_pre7` | Last 7 digits of `phone_std` (e.g., `6277945711` → `7945711`; if < 7 digits, pad with leading zeros) |
| `last_name_std_pre3` | Last 3 characters of `last_name_std` (e.g., `saunders` → `und`, `smith` → `ith`) |
| `first_name_std_pre3` | First 3 characters of `first_name_std` (e.g., `john` → `joh`, `ali` → `ali`) |