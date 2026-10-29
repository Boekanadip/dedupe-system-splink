# Training & Retraining — EM Model Workflow (Splink)

## 1. Training Pipeline

**Entry point:** `src/splink_model.py::train_and_predict(df, verbose=False)`

**Steps:**
1. **Load standardized data** from `data/processed/crm_standardized.parquet`
2. **Build comparison levels** using `build_name_comparison()`, `build_contact_comparison()`, `build_location_comparison()`, `build_dob_comparison()` (see `docs/comparison_levels.md`)
3. **Build Splink Linker** with SettingsCreator incorporating:
   - 11 blocking rules (see `docs/blocking_rules.md`)
   - 4 comparison levels (name, contact, location, dob)
   - m-probabilities and u-probabilities estimated via EM
4. **Run EM training** — converges in 5-8 iterations
5. **Predict on all blocked pairs** → `match_probability`, `decision`
6. **Save outputs**: predictions, entity map, master table

**Key function calls:**
```python
from src.splink_model import train_and_predict
linker, predictions = train_and_predict(df, verbose=False)
```

## 2. Holdout Evaluation

**Script:** `final_eval.py`

**Procedure:**
1. Load gold labels: `data/labels/gold_labels.csv`
2. **Split 80/20 stratified** by label, `random_state=42`
   - `gold_train`: 2,820 pairs (80%)
   - `gold_test`: 705 pairs (20%)
3. **Regenerate predictions** on full dataset
4. **Map pair_id** to join predictions with gold test
5. **Evaluate at thresholds**: 0.35, 0.50, 0.82, 0.84, 0.90
6. **Report**: TP, FP, FN, TN, recall, precision, F1

**Gold split sizes (full gold set):**
- Scored pairs: 3,215 (851 matches, 2,364 non-matches; 378 without probability excluded)
- 80/20 stratified split would yield: ~2,572 train, ~643 test
- Threshold 0.84: recall 0.9976, precision 0.9350, F1 0.9653 (on scored pairs)

## 3. When to Retrain

| Trigger | Action |
|---|---|
| New CSV arrives with different schema | Re-run standardization; verify column map; retrain if m-probabilities shift |
| Recall < target @ threshold | Investigate FN patterns (see `outputs/fn_analysis.md`); adjust m-probabilities; retrain |
| Precision drops significantly | Check for data drift; consider raising Else m-probabilities; retrain |
| Blocking rules change (new columns added) | Update `DEFAULT_BENCHMARK_RULES` in `config.py`; retrain |
| Quarterly maintenance | Re-train on full data; compare metrics to previous version; promote if improved |

## 4. Model Versioning Scheme

```
vYYYYMMDD_HHMMSS  (e.g., v20261027_074552)
  → Stored in: outputs/models/latest.json
  → Config snapshot: outputs/thresholds_override.json
  → Metadata: outputs/version_gold_scores.json
```

**Promotion path:**
1. Train on full data → evaluate on holdout gold
2. If recall ≥ target AND precision stable → `cp latest.json models/vYYYYMMDD_HHMMSS.json`
3. Update `MATCH_THRESHOLD` in `thresholds_override.json` if needed
4. Document changes in `docs/training_retraining.md`

## 5. Incremental / New Data

**Do NOT retrain every time a new CSV arrives** (per AGENTS.md §17).

**Normal flow:**
1. Ingest new data → standardize → add to existing dataset
2. If new records ≤ 20% of total → re-run linker on augmented dataset (fast, ~seconds)
3. If new records > 20% → evaluate recall@threshold on new holdout split
   - If recall maintained → just re-link
   - If recall degraded → retrain from scratch with updated m-probabilities

**Feature store considerations:**
- Standardized columns (`first_name_std`, `last_name_std`, etc.) are **append-only**
- Do NOT overwrite raw columns with standardized values (per AGENTS.md §10)
- Preserve `first_name`, `first_name_std` as separate columns

## 6. Current Model State

| Artifact | Path | Status |
|---|---|---|
| Model settings | `outputs/models/latest.json` | v20261027_fixed (post-fix) |
| Threshold override | `outputs/thresholds_override.json` | match=0.84, review=0.35 |
| Predictions (full) | `outputs/splink_predictions.parquet` | 627 pairs (sampled from 1.5M candidates) |
| Predictions (sample) | `outputs/splink_predictions_sample.parquet` | 10K rows |
| Evaluation report | `outputs/evaluation_report.json` | Not yet generated for v20261027_fixed |