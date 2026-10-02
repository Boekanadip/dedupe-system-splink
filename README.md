# CRM Entity Resolution / Deduplication — Splink + DuckDB

Development dataset: `crm_50000_customers_dirty_v3.csv` (Kaggle Customer 360).
50k is a **development** dataset, not a production capacity claim
(MASTER_CONTEXT §1).

## Quick start

```powershell
python -m src.run_all                      # full 50k, trains a new model version
python -m src.run_all --reuse-model latest # same output, reuses the saved model
python tests/test_smoke.py                 # 20 invariant checks

.venv/Scripts/streamlit run app.py --server.address 0.0.0.0   # upload page (LAN demo)
```

| | trains | `--reuse-model latest` |
|---|---|---|
| `splink_model` | ~120 s | **~6 s** |
| full `run_all` | ~205 s | **~90 s** |

MASTER_CONTEXT §15: *"Do not retrain simply because a new file arrived."*
Reuse is opt-in so a default run always produces a fresh, versioned model.

`outputs/run_summary.json` records per-step timings plus the `model_version`
that produced the artifacts.

## Pipeline

| Step | Command | Output |
|---|---|---|
| 1. Profiling | `python -m src.profiling` | `outputs/profiling_summary.json` |
| 2. Standardization | `python -m src.standardize` | `data/processed/crm_standardized.parquet` |
| 3. Silver labels | `python -m src.labels --silver-only` | `data/labels/silver_pairs.csv` |
| 4. Blocking benchmark | `python -m src.blocking_benchmark --full` | `outputs/blocking_benchmark.csv` |
| 5. Splink model | `python -m src.splink_model --full` | `outputs/splink_predictions.parquet` |
| 6. Review queue | `python -m src.labels --full` | `data/labels/review_queue.csv` |
| 7. Clustering | `python -m src.clustering --full` | `outputs/entity_map.parquet` |
| 8. Master record | `python -m src.master_record` | `outputs/master_customers.parquet` |
| 9. Evaluation | `python -m src.evaluate` | `outputs/evaluation_report.json` |

Supporting commands:

```powershell
python -m src.threshold_eval --full       # per-threshold metrics, by label source
python -m src.labels --promote            # reviewed queue -> gold_labels.csv (backs up the old one)
python -m src.labels --feedback           # reviewed pairs -> feedback.csv
python -m src.model_lifecycle             # list model versions
python -m src.review_sample --band match  # draw pairs for manual review
python -m src.stress_test --pairs 200     # recovery on corrupted duplicates
python -m src.batch_eval                  # cross-batch linkage, entity stability
python -m src.eval_truth --full           # device-truth coverage per rule
python -m src.registry                    # show batches / record_id ownership
python -m src.registry --seed a.csv b.csv # rebuild the registry from scratch
python -m src.validate_upload file.csv    # schema + date-format check before registering
python -m src.incremental                 # link the newest batch to existing entities (no full re-run)
```

## Demo: upload page (Streamlit)

```powershell
.venv/Scripts/streamlit run app.py --server.address 0.0.0.0
```

Flow: upload CSV → validated by `src.validate_upload` (required `first_name`,
`last_name`, ≥1 of `email`/`phone_number`, plus every blocking-key column) →
**only when the register button is clicked** is it saved raw in `data/raw/` and
registered in `data/processed/batch_registry.json` (derives `record_id`
numbering, refuses a re-upload by sha256) → **full pipeline re-run**
(`src.run_all`), then the cross-batch report is shown: matched across batches /
duplicates inside the new batch / wrong merges / old `entity_id` changed.

The page carries a **"Cara kerja"** expander (7 pipeline steps, including where
human review sits) and a **monitoring sidebar** (active model + trained date,
batch count, pending review-queue pairs, last run status). Section 5 shows the
four cross-batch numbers plus artifact paths and next steps.

**Incremental by default (FR-14).** After registering, the page runs
`src.incremental`: only the new batch is standardized, scored and linked to
existing entities — the old data is not re-run. Measured: **5.3 s for a
100-row batch** vs ~90 s for a full re-run. A full `run_all` is only for
retraining (the checkbox) or a first run with no model yet.

**Review page.** A second Streamlit tab (`pages/1_review.py`) shows the human
queue: 457 pairs with side-by-side values, which fields agree, and the model
score. Pick `match` / `no_match`, save, then **Promote** to raise labels to
gold (the old gold is backed up first). Edits go straight to
`review_queue.csv` — fine for a single reviewer.

What the page does instead of guessing or blocking:

- **Day/month order.** If a date column has no row with day > 12 or month > 12,
  the question is asked (`dmy` vs `mdy`). `standardize` refuses to guess —
  `dob_exact` and `city_dob` depend on the answer.
- **No orphans.** The file is written only at register time, so an abandoned or
  re-selected upload leaves nothing on disk. A payload whose sha256 is already
  registered skips registration and only re-runs — retrying after a failed run
  cannot double-count.
- **Model reuse by default** (MASTER_CONTEXT §15): the pipeline scores with the
  last trained model (~90 s). A checkbox retrains on demand (~+120 s); new data
  does not silently replace a validated model.
- **Live log.** The current step and elapsed seconds stream while the pipeline
  runs, instead of a frozen screen.

## Measured results (51,200 rows = 4 registered batches)

```
candidate pairs (union of 12 rules)   306,725
decisions        MATCH 2,973 | REVIEW 46,606 | NON_MATCH 257,146
auto-match rate 0.97% | review rate 15.19% | non-match rate 83.84%
clustered entities                      48,380
cluster sizes              {1: 45704, 2: 2541, 3: 126, 4: 9}
cross-batch (batch_0001 vs the rest)   660   (660 | 1,128 new-batch | 0 wrong | 0 ids moved)
device-truth pairs in one entity  2,938 / 2,938 = 100.00%
  (35 MATCH edges unverifiable: at least one side has no device data)
recovery on 200 corrupted duplicates         200/200 = 100%
entities holding 2 device ids                     0
```

Clustering reproduces the source `customer_id` grouping (48,200 device ids over
48,200 `customer_id` groups, no group carrying two device ids), without
`customer_id` ever being used as a blocking key, a comparison, or a label.

Two uploads were exercised end to end: `batch_0003.csv` (1,000 rows: 900 exact
copies of `batch_0002` rows + 100 with character typos) and `batch_0005.csv`
(200 rows, comma delimiter, ISO dates, no `device_id(s)`). Under the current
model all 1,000 demo rows landed in their source entity — see "Read before
trusting a number" item 9 for why that number moved between model versions.
Reproduce with `python notebooks/make_demo_batch.py` then
`python notebooks/measure_demo_recovery.py`.

## Model lifecycle

MASTER_CONTEXT §16 fixes the layout:

```
models/v20260930_142409/
    model.json        trained Splink model
    metadata.json     what it was trained on, with seed and versions
    thresholds.json   the decision policy it was judged under
    evaluation.json   decisions and rates from that run
models/latest.json    pointer to the newest version
```

Thresholds are stored **with** the model: a score reviewed under different
thresholds would silently change what MATCH means.

## Read before trusting a number

1. **`device_id` is the answer key, not independent evidence.** Measured on this
   file: 48,200 distinct device ids over 48,200 `customer_id` groups, and no
   group carries two device ids. Agreement with it proves the pipeline
   reproduces the source grouping — it proves **nothing** about fuzzy duplicates
   or any other dataset. `signup_date`, `address` and `city` are equally 1:1
   here; the dataset is degenerate, the method is not.
2. **`M_ELSE_LEVEL_FLOOR = 0.05` is an assumption.** This dataset's duplicates are
   identical on every field, so EM learned `m ≈ 0` for "differs", Splink clamped
   it to `8.58e-300`, and the model could not express uncertainty: every
   non-match scored one identical weight and the review band could never be
   non-empty. Pinning the "all other" level opened a gradient — on the current
   51,200-row run that is 27,449 distinct weights and 46,606 pairs in the review
   band, with non-match weights from -309 to -4.8. The value encodes "about 5% of
   true matches differ completely on a field", which cannot be measured from this
   data because it contains no such pair.
3. **`coverage_pct` on silver labels is tautological.** Silver positives are
   defined as exact `phone`+`dob` agreement — the same fields `phone_exact` and
   `dob_exact` block on, so 100% there is arithmetic. The non-tautological
   column is `device_truth_coverage_pct` (82.71%–100% across the 12 rules).
4. **`LAMBDA_RECALL_ASSUMPTION = 0.7` is an assumption**, never measured.
5. **`MATCH_THRESHOLD = 0.9` / `REVIEW_THRESHOLD = 1e-10` are not validated by a
   two-class gold set.** Under the current model all 2,938 device-truth pairs sit
   at `p = 1.0` and none fall below — but that is a property of *this* model
   version, not of the threshold: the previous version left 71 of them in the
   REVIEW band (item 9). Re-measure when data, comparisons, or the m floor change.
6. **`F1 = 1.0` is an artifact, always.** It appears whenever the label set and
   the model agree trivially — silver by construction, or gold with a single
   class. The current gold set is **100 positives / 0 negatives**, so precision
   cannot be estimated from it at all. `src/evaluate` states this per layer.
7. **The honest accuracy number today: n = 100 reviewed MATCH pairs, 0 false
   positives.** With no false positive in 100 samples, the false-positive rate is
   bounded at 3.0% (95% confidence, rule of three). That is the size of the claim,
   not a percentage improvement.
8. **100% recovery on corrupted duplicates is synthetic.** `stress_test` injects
   documented typos into device-truth duplicates in memory. No dataset file is
   written. It measures the model on deliberately damaged records, not on client
   data.
9. **Numbers move when the model is retrained — that is why the app reuses by
   default.** The 100 demo rows with character typos were measured twice: under
   `v20260930_142409` (trained on 50k) 64 of them stayed unmerged and 71
   device-truth pairs scored 5e-6..1e-3 (all decided REVIEW); under
   `v20261001_092908` (trained on 51,200, typos included) all 1,000 demo rows
   landed in their source entity and the review band grew 28,855 → 46,606. Both
   are real measurements; neither is a general typo-handling claim. The smoke
   check therefore asserts invariants (MATCH never split, nothing known lands in
   NON_MATCH, entities never mix device ids) and *reports* the recall number
   instead of encoding a threshold as an invariant.

## Evaluation is reported in four separate layers

`src/evaluate` does not collapse them into one number (DESIGN §17), because
100% blocking coverage with 0% recall is indistinguishable from 100% coverage with
perfect recall if you only report coverage.

| Layer | Question | Measured |
|---|---|---|
| blocking | did candidate generation *contain* the true pairs? | 2,938/2,938 · ceiling 1.0 |
| linkage | did the model *score* them correctly? | 2,938 above threshold · 0 below · 0 false merges · 35 unverifiable (no device data) |
| decision | did thresholds give an acceptable split? | 0.97% auto-match · 15.19% review |
| entity | did one person's records end in one entity? | 2,938 together · 0 split · 0 mixed entities |

Each layer states what it does **not** prove, and a layer without a truth
channel reports `unavailable` rather than `0`.

## Data safety

Raw input is never modified; standardization only adds `_std` columns. Results go
to the project-root `outputs/`, labels to `data/labels/` — both gitignored.
`models/` is tracked deliberately (config and counts only, no record-level data).

Reviewed work is protected three ways: `--promote` backs up the existing
`gold_labels.csv` before overwriting; rebuilding the review queue carries existing
labels forward; `feedback.csv` is append-only and keyed on
`(pair_id, model_version)`.

> **Excel caveat.** Saving a review file from a comma-decimal locale rewrites the
> delimiter to `;` and turns numbers into `2,92E+11`. `src.labels` and
> `src.feedback` detect this, but `match_probability` in the saved file is not
> trustworthy — scores are always re-read from the predictions parquet.
