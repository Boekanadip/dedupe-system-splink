---
name: splink-model
description: Configure and train the unsupervised Splink model, generate probabilities, evaluate thresholds, and cluster entities without changing the core architecture.
---

## Procedure
1. Confirm the configured `record_id` column is unique.
2. Build comparisons appropriate to each field type.
3. Train with an intentionally bounded training block first.
4. Check EM convergence and parameter diagnostics.
5. Run prediction using the selected prediction blocking union.
6. Keep pairwise evidence columns for audit.
7. Evaluate probability thresholds on the gold sample.
8. Cluster only after selecting the pairwise match threshold.

## Interpretation
- `match_probability` is model evidence, not a human-reviewed truth label.
- High probability does not prove correctness without independent validation.
- Cluster quality can be worse than pair quality because transitive clustering propagates pair decisions.
