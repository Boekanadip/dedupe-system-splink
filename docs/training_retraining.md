# Training & Retraining — EM Model Workflow (Splink)

## 1. Training Pipeline

**Entry point:** `src/splink_model.py::train_and_predict(df, verbose=False)`

**Steps:**
1. **Load standardized data** from `data/processed/crm_standardized.parquet`
2. **Build comparison levels** using `build_name_comparison()`, `build_contact_comparison()`, `build_location_comparison()`, `build_dob_comparison()` (see `docs/comparison_levels.md`)
3. **Build Splink Linker** with SettingsCreator incorporating:
   - 12 blocking rules (see `docs/blocking_rules.md`)
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
3. **Regenerate predictions** on full dataset
4. **Map pair_id** to join predictions with gold test
5. **Evaluate at thresholds**: 0.35, 0.50, 0.82, 0.84, 0.90
6. **Report**: TP, FP, FN, TN, recall, precision, F1

**Gold set saat ini:**
- `gold_labels.csv`: 3.890 pasangan (1.372 `match`, 2.518 `no_match`)
- 3.512 pasangan memiliki `match_probability`; 378 pasangan tanpa skor
- Snapshot historis di `outputs/gold_scored.parquet`: 3.215 pasangan. Angka split dan metrik di `docs/reports/final_eval_report.md` dihitung dari snapshot lama ini; regenerasi diperlukan sebelum dipakai sebagai metrik model aktif.

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
vYYYYMMDD_HHMMSS  (e.g., v20261116_122048)
  → Stored in: models/<version>/ (model.json, metadata.json, thresholds.json, evaluation.json)
  → Pointer: models/latest.json (hanya diperbarui oleh run non-`sample`)
  → Threshold default: src/config.py; override opsional di outputs/thresholds_override.json
```

**Promotion path:**
1. Train on full data → evaluate on holdout gold
2. If recall ≥ target AND precision stable → model tersimpan otomatis di `models/vYYYYMMDD_HHMMSS/`
3. Update `MATCH_THRESHOLD` hanya jika evaluasi mendukung
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
| Model pointer | `models/latest.json` | `v20261027_074552` (run `full` terakhir) |
| Model sample terbaru | `models/v20261116_122048/` | scope `sample`, 10.000 input, 5.289 pasangan |
| Threshold override | `outputs/thresholds_override.json` | Tidak ada; default match=0.84, review=0.35 di `src/config.py` |
| Predictions | `outputs/splink_predictions.parquet` | 200 pasangan pada artefak saat ini |
| Predictions (sample) | `outputs/splink_predictions_sample.parquet` | Ada |
| Evaluation report | `outputs/evaluation_report.json` | Ada; scope `sample`, model `v20261116_122048` |