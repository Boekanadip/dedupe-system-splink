# How to use the AI agent safely

## Good prompts
- "Run profiling only. Do not change the architecture."
- "Inspect the actual CSV columns and tell me exactly what must change in COLUMN_MAP."
- "Add a new blocking candidate and benchmark it on the smoke sample before using it in prediction."
- "Compare these thresholds on the gold set; do not choose one without metrics."
- "Explain why this candidate pair was scored highly using the evidence columns."

## Bad prompts
- "Make the model as accurate as possible" without an evaluation set.
- "Use any ML method you think is better" when the PoC architecture is already fixed.
- "Add fuzzy matching everywhere" without measuring candidate growth.
- "The F1 is 1.0, so the model is done." Silver labels are the easy cases by
  construction; 1.0 there is an artifact, not a result.

## Module map
| Module | Role |
|---|---|
| `src/profiling.py` | schema, nulls, duplicates, formatting anomalies, identifier coverage |
| `src/standardize.py` | normalized `*_std` fields and lossy blocking keys |
| `src/labels.py` | silver pairs, review queue, gold promotion, label loading |
| `src/blocking_benchmark.py` | per-rule pairs, union, skew, coverage |
| `src/splink_model.py` | u/EM estimation, pair probabilities |
| `src/clustering.py` | union-find over matched edges -> `entity_id` |
| `src/master_record.py` | per-entity master values plus lineage |
| `src/threshold_eval.py` | precision/recall/F1 per threshold |
| `src/run_all.py` | ordered end-to-end run, writes `run_summary.json` |

## Scope discipline
Every artifact has a `<name>.meta.json` recording `scope` (`sample` or `full`).
`clustering`, `master_record` and `threshold_eval` refuse to mix scopes. A
`--sample` run cannot overwrite a `full` entity map unless `--force` is passed,
because a sample run still emits every `record_id` and so looks complete while
silently inventing ~1,700 entities.

## Agent deliverable format
When changing the pipeline, the agent should report:
1. files changed;
2. reason for the change;
3. measured before/after counts;
4. runtime impact;
5. known limitations;
6. exact command used for verification.
