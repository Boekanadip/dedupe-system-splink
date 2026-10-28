---
name: dedup-workflow
description: Execute or modify the CRM deduplication PoC while preserving the probabilistic entity-resolution architecture, evidence-based thresholds, and auditability.
---

## When to use
Use for any task involving architecture, pipeline changes, training, prediction, thresholding, clustering, or demo behavior in this repository.

## Workflow
1. Read `AGENTS.md` and `docs/DESIGN.md`.
2. Inspect the actual schema before assuming column names.
3. Use `src/config.py` for source-column mappings and paths.
4. Keep raw columns intact and add standardized columns.
5. Preserve `record_id` semantics.
6. Benchmark blocking before full prediction.
7. Use Splink/DuckDB for probabilistic linkage.
8. Keep manual labels for validation/evaluation, not as hidden training labels.
9. Report measured counts and runtimes.
10. For threshold changes, show evaluation impact before adopting them.

## Forbidden shortcuts
- Do not use `customer_id` as the sole duplicate truth.
- Do not compare all 50k records pairwise in Python.
- Do not replace probabilistic linkage with a generic classifier without explicit approval.
- Do not silently widen blocking to improve apparent recall.
- Do not silently remove fields because of nulls; first quantify the effect.
