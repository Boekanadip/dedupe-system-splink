#!/usr/bin/env python3
import pandas as pd

# Load gold labels (test set 20%)
gold = pd.read_csv("data/labels/gold_labels.csv")
gold["is_match"] = gold["label"].map({"match": True, "no_match": False})

# Load predictions
preds = pd.read_parquet("outputs/splink_predictions.parquet")

# Merge
merged = preds.merge(gold[["record_id_l", "record_id_r", "is_match"]], on=["record_id_l", "record_id_r"])

# Evaluate thresholds
results = []
for thresh in [0.86, 0.87, 0.88, 0.89]:
    preds_bin = (merged["match_probability"] >= thresh).astype(int)
    tp = ((preds_bin == 1) & (merged["is_match"] == 1)).sum()
    fp = ((preds_bin == 1) & (merged["is_match"] == 0)).sum()
    fn = ((preds_bin == 0) & (merged["is_match"] == 1)).sum()
    tn = ((preds_bin == 0) & (merged["is_match"] == 0)).sum()
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    results.append({
        "threshold": thresh,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "tn": int(tn),
        "total_pairs": len(merged)
    })

df = pd.DataFrame(results)
print(df.to_string(index=False))
df.to_json("outputs/threshold_comparison_20261027.json", orient="records", indent=2)
print("\nSaved: outputs/threshold_comparison_20261027.json")
