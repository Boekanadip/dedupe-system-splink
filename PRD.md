# PRD.md
# CRM Entity Resolution / Deduplication System

## 1. Product Goal

Build an Entity Resolution system capable of identifying records that
refer to the same real-world customer/entity.

The system is initially developed and evaluated using a 50k-record
Customer 360 dataset.

The 50k dataset is a development dataset, not the intended production
scale.

The eventual system is expected to process client/company data whose:

- volume is unknown;
- schema may differ;
- data quality may vary;
- records may arrive incrementally;
- duplicate patterns may evolve.

---

# 2. Core Problem

Organizations may receive multiple records representing the same
customer/entity.

Examples:

Record A:

John Smith
john.smith@gmail.com
08123456789

Record B:

Jhon Smith
john.smith@gmail.com
+628123456789

These records may represent the same real-world entity even though
their values are not identical.

The system must identify such relationships probabilistically rather
than relying only on exact equality.

---

# 3. Main Functional Requirements

## FR-01 Input

The system must accept customer/entity records from CSV or equivalent
tabular sources.

The input schema must be validated.

The system must not assume that the source customer_id is unique.

---

## FR-02 Record Identity

Every physical input record must have a unique internal record_id.

If the source does not provide one, the system must generate it.

---

## FR-03 Raw Data Preservation

Original source values must be preserved.

Standardized values must be stored separately.

---

## FR-04 Standardization

Before linkage, incoming data must pass through a standardization
layer.

Standardization should be configurable by field/source.

---

## FR-05 Feature Engineering

The system must generate linkage-relevant derived features where
justified.

---

## FR-06 New-Batch Deduplication

A newly arriving dataset should first be examined for duplicates
within the batch.

This step should use the configured Entity Resolution engine.

---

## FR-07 Existing Entity Linkage

Newly resolved entities must be linked against the existing master/entity
population.

---

## FR-08 Decision

Each candidate/entity relationship should result in a decision such as:

- MATCH
- REVIEW
- NEW / NON-MATCH

The exact decision policy must be configurable.

---

## FR-09 Human Review

Pairs requiring review must be placed into a review queue.

Review results must be stored and reusable for evaluation and future
model improvement.

---

## FR-10 Entity ID

Records determined to represent the same real-world entity must share
the same entity_id.

---

## FR-11 History

The system must preserve linkage history and source lineage.

---

## FR-12 Evaluation

The system must support evaluation using reviewed/gold pairs where
available.

Metrics should include, where applicable:

- precision
- recall
- F1
- false positives
- false negatives
- review rate
- auto-match rate
- candidate volume
- runtime

---

## FR-13 Model Lifecycle

The system must support versioned model/configuration artifacts.

Retraining must be possible without rebuilding the entire application
from scratch.

---

## FR-14 Incremental Processing

New data should be processable without reprocessing all historical
raw data unnecessarily.

---

## FR-15 Monitoring

The eventual system should support monitoring for:

- data quality
- data drift
- match rate
- review rate
- non-match rate
- false positive/negative feedback
- runtime
- candidate volume

---

# 4. Non-Functional Requirements

## Scalability

The system must not assume that production data is limited to 50k
records.

---

## Maintainability

Standardization, feature engineering, blocking, comparison logic,
decision policy, model configuration, and execution backend should be
separated where practical.

---

## Explainability

The system should retain enough evidence to explain why a pair/entity
relationship received its score and decision.

---

## Reproducibility

A model/configuration version should be reproducible from its saved
configuration and metadata.

---

## Extensibility

The system should allow:

- additional data sources
- additional fields
- alternative blocking strategies
- alternative comparison methods
- model updates
- backend scaling
- alternative ER engines

without rewriting the entire pipeline.

---

# 5. Out of Scope for Initial Development

The following are not required immediately:

- production deployment infrastructure
- distributed cluster deployment
- real client integration
- automated scheduling
- full production database infrastructure
- production dashboard

However, the architecture should not make these future requirements
unnecessarily difficult.

---

# 6. Success Criteria

The development system is successful when it demonstrates:

1. Reliable data profiling.
2. Reusable standardization.
3. Feature engineering with clear rationale.
4. Efficient blocking.
5. Probabilistic entity resolution.
6. Meaningful evaluation.
7. Explainable match evidence.
8. MATCH/REVIEW/NEW decisioning.
9. New-batch deduplication.
10. New-to-existing-entity linkage.
11. Entity ID assignment.
12. Human feedback capture.
13. Versioned model/configuration.
14. A clear path toward larger production data.

---

# 7. PoC Status (2026-10-01)

State of the development PoC: 51,200 rows across 4 registered batches (the
original 40k, a 10k file, a 1,000-row demo upload, and a 200-row comma-delimited
client-style file). Every number is a saved artifact, not a target. Note:
earlier notes referred to "PRD §8"; before this revision the document had no
section 7 or 8, so the status section is numbered 7 and the upload requirements
are §8.

| # | Success criterion | Status | Evidence |
|---|---|---|---|
| 1-4 | Profiling / standardization / features / blocking | done | `outputs/profiling_summary.json`, `data/processed/*.meta.json`, `outputs/blocking_benchmark.csv` |
| 5-8 | ER, evaluation, explainability, MATCH/REVIEW/NON_MATCH | done | `outputs/evaluation_report.json` (4 layers, each with caveats) |
| 9 | New-batch deduplication | done | `outputs/batch_linkage_report.json`: 660 cross-batch, 1,128 inside the newer batches, 0 wrong merges |
| 10 | New-to-existing-entity linkage | done | same report: 0 of 40,000 old `entity_id` changed; demo run with `--first-record-id rec_050001` matched 999 demo pairs to existing entities |
| 11 | Entity ID assignment | done | `outputs/entity_map.parquet`, 48,380 entities from 51,200 records |
| 12 | Human feedback capture | done | `data/labels/review_queue.csv`, `feedback.csv`, `gold_labels.csv` |
| 13 | Versioned model/config | done | `models/v20261001_092908/` (latest) + `latest.json`; `v20260930_142409` kept as history |
| 14 | Path to larger data | partial | blocking benchmarked (candidate count, coverage, runtime); incremental linkage implemented (`src.incremental`, 5.3 s per 100-row batch); **not** tested beyond 51,400 |

Demo surface: `app.py` (Streamlit) — upload → validate → register batch →
full re-run. See README "Demo: upload page". Two uploads were exercised end to
end: `batch_0003.csv` (1,000 rows) and `batch_0005.csv` (200 rows, comma
delimiter, ISO dates, no `device_id(s)`). Both validated, registered, and
linked; under the current model all 1,000 demo rows rejoined their source
entity. The earlier model version left 71 device-truth pairs in REVIEW — the
numbers moved because the model was retrained, which is why the page reuses the
last model by default (MASTER_CONTEXT §15).

Known limits, stated rather than hidden:

- Accuracy claims rest on `device_id`/`customer_id` grouping that is
  degenerate on this dataset (README "Read before trusting a number").
- Day/month order for a column with no unambiguous rows cannot be derived
  and is asked, not guessed.
- `record_id` is positional per batch; a file edited after registration is
  detected via sha256, not prevented.
- Incremental processing (FR-14) is currently "re-run the whole pipeline
  after each upload"; scoring only the new batch is not implemented.
- Multi-field damage is model-version dependent, not a fixed capability: under
  `v20260930_142409` a demo row with typos in 3 fields rejoined its source
  entity in 31 of 90 cases (2 fields: 5 of 10; untouched: 900 of 900); under
  `v20261001_092908` all 1,000 demo rows merged. Neither number is a general
  typo-handling claim.

---

# 8. Upload & Demo Requirements

Extra requirements for the `app.py` upload surface, added after the PoC was
built. Extends FR-01 / FR-02 / FR-14; it does not replace them.

## 8.1 Enforced input schema

A batch is refused **before** it is registered when any column below is
absent. Derived from the active blocking rules in `src/config.py`, not
hand-written, so the validator and `src.standardize` cannot disagree.

| Status | Columns | Why |
|---|---|---|
| required | `first_name`, `last_name` | name comparison + blocking |
| required (blocking) | `email`, `phone_number` | at least one is the strongest link; both are blocking keys |
| required (blocking) | `address`, `city`, `state`, `dob` | active rules `city_dob`, `dob_exact`, `address_city`, `name_prefix_state`, `city_state_dob_year` |
| optional | `signup_date`, `country`, `gender`, `source`, `customer_id`, `device_id(s)` | add evidence or lineage, block nothing |
| optional | `customer_id` | recorded as `source`, never used as a blocking key, comparison, or label |

> **Correction to the earlier sketch.** An earlier note said `dob` / `address` /
> `city` were "optional but helpful". They are not optional today: they are
> blocking keys, and `src/standardize.py:227` refuses a dataset whose blocking
> keys cannot be derived. A validator that only warned would promise acceptance
> the pipeline then revokes after the batch was registered. Making them
> optional is a real change to `BENCHMARK_RULES`, not a UI change — it is
> recorded here as open, not as done.

Delimiter and encoding are detected, not assumed (`;` and `,` both work,
`utf-8` with `latin-1` fallback).

## 8.2 Day/month decision must not be guessed

`dob` and `signup_date` may be d/m/Y or m/d/Y. The order is derived only from
rows where day > 12 or month > 12. When a column contains neither, the upload
page asks (`dmy` / `mdy`) and passes the answer to `standardize`. `dob_exact`
and `city_dob` depend on this answer, so a silent guess is not permitted.

## 8.3 Batch registration and record_id durability

- Every upload is stored raw, unmodified, as `batch_NNNN.csv` in `data/raw/`.
  The file is written **only when the register button is clicked** — an
  abandoned or re-selected upload leaves nothing on disk.
- `record_id` ranges are derived from `data/processed/batch_registry.json`, never
  typed in by a user; re-uploading identical bytes is refused by sha256, and a
  payload that is already registered skips registration and only re-runs the
  pipeline (a retry after a failed run cannot double-count).
- Editing a registered file shifts the `record_id` of later rows. The sha256
  makes that detectable, not impossible.

## 8.4 Demo scope

- Runs on the LAN: `streamlit run app.py --server.address 0.0.0.0`.
- After registering, the page runs the **full** pipeline and reports the four
  cross-batch numbers: matched across batches, duplicates inside the new batch,
  wrong merges, old `entity_id` changed.
- The pipeline reuses the last trained model by default (MASTER_CONTEXT §15:
  new data must not silently retrain); retraining is an explicit on-demand
  control, not a per-upload side effect.
- **Incremental by default (FR-14):** `src.incremental` standardizes, scores and
  links only the new batch to existing entities — the old data is not re-run.
  A full `run_all` is for retraining or a first run with no model.
- **Review page:** a second Streamlit tab (`pages/1_review.py`) shows the human
  queue with side-by-side values and per-field agreement. Reviewers pick
  `match` / `no_match`, save, and promote to gold (old gold backed up first).
  Edits write straight to `review_queue.csv` (single-reviewer assumption).
- No authentication, no scheduling, no production deployment (still §5).
- Every accuracy number on the page inherits the README caveats; the page must
  not present `F1 = 1.0` or a 100% coverage figure as a quality claim.