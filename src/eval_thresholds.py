import pandas as pd
from pathlib import Path

# Load predictions
pred_df = pd.read_parquet(r"C:\Users\User\Downloads\dedup-system-splink\outputs\splink_predictions.parquet")
gold = pd.read_csv(r"C:\Users\User\Downloads\dedup-system-splink\data\labels\gold_labels.csv")

# Map pair_id
pred_df["pair_id"] = pred_df["record_id_l"].astype(str) + "_" + pred_df["record_id_r"].astype(str)
gold["pair_id"] = gold["record_id_l"].astype(str) + "_" + gold["record_id_r"].astype(str)

# Create label map
label_map = dict(zip(gold["pair_id"], gold["label"]))
pred_df["gold_label"] = pred_df["pair_id"].map(label_map)

# Thresholds
thresholds = [0.86, 0.87, 0.88, 0.89]
results = []

for t in thresholds:
    # Select REVIEW pairs and apply threshold
    review_df = pred_df[pred_df["decision"] == "REVIEW"].copy()
    review_df["predicted_match"] = review_df["match_probability"] >= t
    
    tp = int((review_df["predicted_match"] & (review_df["gold_label"] == "match")).sum())
    fp = int((review_df["predicted_match"] & (review_df["gold_label"] == "non-match")).sum())
    fn = int((~review_df["predicted_match"] & (review_df["gold_label"] == "match")).sum())
    tn = int((~review_df["predicted_match"] & (review_df["gold_label"] == "non-match")).sum())
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    results.append({
        "threshold": t,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4)
    })
    print(f"Threshold {t}: TP={tp}, FP={fp}, FN={fn}, TN={tn}")
    print(f"  Precision={precision:.4f}, Recall={recall:.4f}, F1={f1:.4f}")
    print()

# Also include already-classified MATCH
match_df = pred_df[pred_df["decision"] == "MATCH"].copy()
print(f"Already classified MATCH: {len(match_df)} pairs")
print(f"  match_probability range: {match_df['match_probability'].min():.4f} - {match_df['match_probability'].max():.4f}")

# Save results
output_path = r"C:\Users\User\Downloads\dedup-system-splink\outputs\threshold_comparison_20261027.json"
with open(output_path, "w") as f:
    json.dump({"results": results}, f, indent=2)
print(f"\nResults saved to {output_path}")