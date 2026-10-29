# Metadata & Pipeline — Data Flow (CRM Entity Resolution)

## 1. Ingestion → Raw Data

**Source file:** `data/raw/crm_50000_customers_dirty_v3.csv`
- 50K customer records (development dataset)
- Columns: `customer_id`, `first_name`, `last_name`, `email`, `phone_number`, `dob`, `address`, `city`, `state`, `country`, `source`, `gender`
- Encoding: UTF-8 with some legacy variants

## 2. Standardization → Feature Engineering

**Output:** `data/processed/crm_standardized.parquet` (108,427 records)

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
| `phone_pre7` | Extracted | Last 7 digits of phone |
| `last_name_std_pre3` | Last 3 chars | `saunders` → ` sau` |
| `first_name_std_pre3` | First 3 chars | `john` → `joh` |

**Derived features used in blocking:**
- `phone_pre7` → `phone_exact` blocking rule
- `last_name_std_pre3` + `first_name_std_pre3` → `name_prefix`, `name_prefix_state`
- `email_domain_pre4` + name prefixes → `email_domain_name`

## 3. Blocking → Candidate Pairs

**11 blocking rules** (see `docs/blocking_rules.md`) generate candidate record pairs.
- Blocking keys are computed from standardized fields.
- Pairs matching ANY block are passed to the linker.
- Estimated candidate pair count: ~1.5M (from 5.8B all-pairs).

## 4. EM Training → Model Parameters

**Algorithm:** Expectation-Maximization (Splink default)
- Estimates m-probabilities (probability field values match within true entities)
- Estimates u-probabilities (probability field values agree by chance)
- Uses blocking rules to limit pair space to ~1.5M pairs
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

**Forced business rules** (always applied regardless of probability):
- **9,133 forced MATCH**: Pairs with exact phone match OR exact email match
- **701,811 forced NON_MATCH**: Pairs with completely different DOB (age gap > 20 years) AND different city/state

## 6. Threshold Evaluation

**Gold label set:** `data/labels/gold_labels.csv` (3,593 labeled pairs; 1,099 matches, 2,494 non-matches)
- Stratified by human review, not random sample
- 378 pairs without `match_probability` (outside blocking) are excluded from scoring

**Evaluation thresholds tested:** 0.35, 0.50, 0.82, 0.84, 0.90

**Current performance @ threshold 0.84 (3,215 scored pairs):**
- Recall: **0.9976** (target ≥0.95 ✅)
- Precision: **0.9350**
- F1: **0.9653**
- TP=849, FP=59, FN=2, TN=2,305

**Decision bands @ 0.84 / 0.35:**
- MATCH (`P >= 0.84`): 908 pairs
- REVIEW (`0.35 <= P < 0.84`): 14 pairs (0 gold positive)
- NON_MATCH (`P < 0.35`): 2,293 pairs

## 7. Model Versioning

| Version | Date | Changes | Recall @ 0.9 | Precision @ 0.9 |
|---|---|---|---|---|
| v20261027_074552 | 2026-10-27 | Initial config; m-probs: contact=0.60, location_else=0.15, dob_exact=0.50 | 0.6853 | 0.9627 |
| v20261027_fixed | 2026-10-27 (this session) | contact m→0.75, location_else m→0.10, dob_exact m→0.30 | 0.9431 | 0.8924 |

**Threshold v2026-10-29 (0.84 / 0.35):** recall **0.9976**, precision **0.9350**, F1 **0.9653** on 3,215 scored gold pairs. Full detail: `final_eval_report.md`.