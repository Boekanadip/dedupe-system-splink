# Metadata & Pipeline — Data Flow (CRM Entity Resolution)

## 1. Ingestion → Raw Data

**Source file:** batch CSV lokal yang terdaftar di `data/raw/`; nama dan jumlah batch dapat berbeda antar lingkungan
- 50K customer records (development dataset)
- Columns: `customer_id`, `first_name`, `last_name`, `email`, `phone_number`, `dob`, `address`, `city`, `state`, `country`, `source`, `gender`
- Encoding: UTF-8 with some legacy variants

## 2. Standardization → Feature Engineering

**Output:** `data/processed/crm_standardized.parquet` (artefak lokal; jumlah record bergantung input)

| Raw Column | Standardized Column | Transformation |
|---|---|---|
| `first_name` | `first_name_std` | lowercase, strip whitespace, remove special chars |
| `last_name` | `last_name_std` | lowercase, strip whitespace, remove special chars |
| `email` | `email_std` | lowercase, normalize |
| `phone_number` | `phone_std` | keep digits only, format: `6277945711` |
| `dob` | `dob_std` | parse to YYYY-MM-DD |
| `city` | `city_std` | lowercase, strip |
| `state` | `state_std` | uppercase 2-letter code |
| `email_domain_pre4` | Extracted | First 4 chars of domain (e.g., `gmail`, `yahoo`) |
| `phone_pre7` | Extracted | First 7 digits of phone |
| `phone_last4` | Extracted | Last 4 digits of phone |
| `dob_year_std` | Extracted | First 4 chars of `dob_std` (year) |
| `last_name_std_pre3` | Extracted | First 3 chars (`saunders` → `sau`) |
| `first_name_std_pre3` | Extracted | First 3 chars (`john` → `joh`) |
| `phonetic_last_name`, `phonetic_first_name` | Extracted | Soundex of standardized names |

**Derived features used in blocking:**
- `phone_pre7` → `phone_prefix`
- `last_name_std_pre3` + `first_name_std_pre3` → `name_prefix`
- `phone_last4` + `dob_year_std` → `phone_last4`
- `last_name_std_pre3` + `phone_last4` → `name_fuzzy_last4`

## 3. Blocking → Candidate Pairs

**12 blocking rules** (see `docs/blocking_rules.md`) generate candidate record pairs.
- Blocking keys are computed from standardized fields.
- Pairs matching ANY block are passed to the linker.
- Union pada eksperimen 40k: **86.699 pasangan kandidat** (`outputs/blocking_benchmark.csv`). Jumlah pada data penuh bergantung batch yang diproses.

## 4. EM Training → Model Parameters

**Algorithm:** Expectation-Maximization (Splink default)
- Estimates m-probabilities (probability field values match within true entities)
- Estimates u-probabilities (probability field values agree by chance)
- Uses blocking rules to limit the pair space to the union kandidat di atas
- Converges in 5-8 iterations typically

**Model artifacts saved:**
- `outputs/entity_map.parquet` — entity resolution link results
- `outputs/master_customers.parquet` — resolved/master entity table
- `outputs/splink_predictions.parquet` — pair-level predictions (match_probability, decision)
- `outputs/splink_predictions_sample.parquet` — 10K row sample

## 5. Prediction → Match/Review/Non-Match

**Output decisions** (from `match_probability` threshold):

| Decision | Condition | Typical use |
|---|---|---|
| `MATCH` | `match_probability >= MATCH_THRESHOLD` (0.84) | Auto-merge into master table |
| `REVIEW` | `REVIEW_THRESHOLD (0.35) <= match_probability < MATCH_THRESHOLD (0.84)` | Human review queue |
| `NON_MATCH` | `match_probability < REVIEW_THRESHOLD` (0.35) | Auto-reject |

**Business rules** (menandai `business_rule`; `unverified_dob` juga menimpa `decision` menjadi `REVIEW`):
- `strong_agreement_email_name_address`: `email_std`, `first_name_std`, `last_name_std`, `address_std` sama **dan** `dob_std` sama.
- `unverified_dob`: empat field identitas sama tetapi `dob_std` beda/kosong → `decision` dipaksa `REVIEW`.
- `no_field_agreement`: tidak ada field di `ZERO_EVIDENCE_FIELDS` yang cocok.
- `conflicting_email_fullname`: `email_std`, `first_name_std`, dan `last_name_std` ketiganya berbeda.

Aturan di atas tidak lagi memaksa `MATCH`/`NON_MATCH` secara global; `match_probability` dan threshold tetap sumber keputusan utama, kecuali override `unverified_dob`.

## 6. Threshold Evaluation

**Gold label set:** `data/labels/gold_labels.csv` (**3.890 pasangan**; 1.372 `match`, 2.518 `no_match`)
- Stratified by human review, not random sample
- 3.512 pasangan memiliki `match_probability`; 378 pasangan tanpa skor (di luar blocking) tidak dihitung

**Tabel historis di bawah memakai snapshot lama `outputs/gold_scored.parquet` (3.215 pasangan). Regenerasi dengan `python -m src.threshold_eval --source gold` sebelum memakai angkanya sebagai metrik model aktif.**

**Evaluation thresholds tested:** 0.35, 0.50, 0.82, 0.84, 0.90

**Snapshot lama @ threshold 0.84 (3,215 scored pairs):**
- Recall: **0.9976** (target ≥0.95 ✅)
- Precision: **0.9350**
- F1: **0.9653**
- TP=849, FP=59, FN=2, TN=2,305

**Decision bands @ 0.84 / 0.35 (snapshot lama):**
- MATCH (`P >= 0.84`): 908 pairs
- REVIEW (`0.35 <= P < 0.84`): 14 pairs (0 gold positive)
- NON_MATCH (`P < 0.35`): 2,293 pairs

## 7. Model Versioning

| Version | Scope | Date | Changes / catatan |
|---|---|---|---|
| v20261027_074552 | full | 2026-10-27 | Initial config; 11 aturan lama; m-probs: contact=0.60, location_else=0.15, dob_exact=0.50. Runtime 26,7 s, 1.522.960 pasangan. |
| v20261116_122048 | sample | 2026-11-16 | 12 aturan aktif; 10.000 baris input, 5.289 pasangan; runtime 1,58 s. Tidak memperbarui `models/latest.json` karena scope `sample`. |

`models/latest.json` saat ini masih menunjuk `v20261027_074552` (satu-satunya run `full`). Angka recall/precision historis ada di `docs/reports/final_eval_report.md` dan harus dihitung ulang terhadap gold terbaru.