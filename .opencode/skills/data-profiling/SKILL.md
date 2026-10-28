---
name: data-profiling
description: Profile the dirty CRM input before modeling, including schema, nulls, uniqueness, duplicates, formats, and identity-signal quality.
---

## Procedure
1. Load the configured CSV.
2. Print shape and dtypes.
3. Validate expected/available columns.
4. Count nulls and unique values.
5. Count exact duplicate rows.
6. Analyze duplicated source `customer_id` values.
7. Inspect representative dirty values in names, phone, email, address and device IDs.
8. Quantify formatting anomalies instead of guessing.
9. Save a machine-readable profiling summary to `outputs/profiling_summary.json` and a human-readable report to `outputs/profiling_report.csv`.

## Rules
- Never mutate the raw file.
- Never invent missing columns.
- Every proposed standardization rule must be traceable to a profiling finding.
