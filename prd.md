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

The system must accept customer/entity records from CSV and verified
tabular database sources.

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

Incremental runs must use a stable source/table watermark, retain a
retryable batch when processing fails, and stage proposed entity changes
for human review before applying them.

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

## FR-16 Database Ingestion

The system should ingest records from a read-only database source into
the existing batch pipeline without modifying the source table.

The initial verified database sources are local DuckDB files and
PostgreSQL. Other scanner backends must be separately tested before
being treated as supported.

Database ingestion must:

- validate/map the source schema to pipeline columns;
- preserve source values in the exported batch;
- support a persisted `updated_at` watermark for new rows;
- avoid advancing a deferred watermark until the complete staged job
  succeeds;
- provide a separate refresh path for changes to records already
  ingested;
- avoid embedding credentials in tracked configuration or logs.

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

# 7. Implementation and Test Status (2026-10-14)

This is an observed development snapshot, not a production certification.
Evidence is from the local working copy and its generated artifacts; data
and outputs are ignored by Git and are not supplied by a clean clone.

| Area | Observed status | Evidence / limitation |
|---|---|---|
| CSV upload and batch registration | implemented | `app.py`, `src/validate_upload.py`, `src/registry.py` |
| Standardization and probabilistic linkage | implemented | `src/standardize.py`, `src/splink_model.py`, `src/incremental.py` |
| Review, feedback, entity/master, and model lifecycle | implemented | `pages/`, `src/labels.py`, `src/feedback.py`, `src/clustering.py`, `src/master_record.py`, `src/model_lifecycle.py` |
| Database ingestion | verified for this test with PostgreSQL; local DuckDB is also used by the pipeline | `src/db_source.py`, `src/db_export.py`, `src/job_run.py`; other scanner backends are not verified |
| PostgreSQL Docker integration | passed for 75 synthetic new rows | `outputs/job_run_summary.json`: status `succeeded`, incremental stage took 6.6 s (job total 6.82 s), 75 staged records |
| Synthetic duplicate check | passed for two selected pairs | `outputs/staging/batch_0018.csv.predictions.parquet`: exact duplicate and near-duplicate each scored `MATCH`, probability 1.0; this is not a quality metric |
| Human gate | pending by design | The 75 staged proposals have not been applied to entity/master artifacts |
| Local standardized dataset | 103,858 records | `data/processed/crm_standardized.parquet`; a local artifact, not part of the repository |
| Smoke test | 43/44 checks passed | `tests/test_smoke.py`; `incremental_candidate_prefilter_is_exact` reported one MATCH edge difference between candidate prefilter and full scoring |
| Production scale, independent accuracy, and deployment | not verified | Synthetic DB test and local development data do not establish these properties |

Known limitations and follow-up:

- Resolve and rerun the failing candidate-prefilter invariant before claiming
  the smoke suite is clean.
- Review the pending staged proposals before applying any entity changes.
- The watermark filter is strict `updated_at > saved_watermark`; rows updated
  with an equal or older timestamp require the separate refresh path and are
  not discovered by that incremental export.
- Date order cannot be inferred where all date values are ambiguous; supply
  `--date-order dmy` or `--date-order mdy` rather than guessing.
- `record_id` values are allocated by registered batch order. Registered input
  file contents must not be edited in place.
- Evaluation labels and synthetic examples are not independent evidence of
  generalization to real customer data.

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