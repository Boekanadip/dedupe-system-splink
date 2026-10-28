import pandas as pd
import json

pred_df = pd.read_parquet(r"C:\Users\User\Downloads\dedup-system-splink\outputs\splink_predictions.parquet")
gold = pd.read_csv(r"C:\Users\User\Downloads\dedup-system-splink\data\labels\gold_labels.csv")

# Map pair_id
pred_df["pair_id"] = pred_df["record_id_l"].astype(str) + "_" + pred_df["record_id_r"].astype(str)
gold["pair_id"] = gold["record_id_l"].astype(str) + "_" + gold["record_id_r"].astype(str)

label_map = dict(zip(gold["pair_id"], gold["label"]))
pred_df["gold_label"] = pred_df["pair_id"].map(label_map)

total_matches_gold = int((pred_df["gold_label"] == "match").sum())
total_nonmatches_gold = int((pred_df["gold_label"] == "non-match").sum())
print(f"Gold set: {total_matches_gold} matches, {total_nonmatches_gold} non-matches")
print(f"Total pairs in predictions: {len(pred_df)}")
print()

# Current classification
match_df = pred_df[pred_df["decision"] == "MATCH"]
review_df = pred_df[pred_df["decision"] == "REVIEW"]
nonmatch_df = pred_df[pred_df["decision"] == "NON_MATCH"]

print(f"Current classification:")
print(f"  MATCH: {len(match_df)} pairs")
print(f"  REVIEW: {len(review_df)} pairs")
print(f"  NON_MATCH: {len(nonmatch_df)} pairs")
print()

# Evaluate at various thresholds by promoting REVIEW pairs
# Threshold works on match_probability: prob >= t -> MATCH, prob < t -> NON_MATCH
thresholds = [0.80, 0.82, 0.84, 0.85, 0.86, 0.87, 0.88, 0.89, 0.90]
results = []

for t in thresholds:
    # Reclassify ALL pairs: prob >= t -> MATCH, prob < t -> NON_MATCH (no REVIEW)
    pred_df["pred_match_at_t"] = pred_df["match_probability"] >= t
    
    # Compute TP/FP/FN/TN vs gold
    # Use .values to get numpy arrays for & operator
    pred_match = pred_df["pred_match_at_t"].values
    gold_match = (pred_df["gold_label"] == "match").values
    gold_nonmatch = (pred_df["gold_label"] == "non-match").values
    
    tp = int((pred_match & gold_match).sum())
    fp = int((pred_match & gold_nonmatch).sum())
    fn = int((~pred_match & gold_match).sum())
    tn = int((~pred_match & gold_nonmatch).sum())
    
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

# Save proper results
output_path = r"C:\Users\User\Downloads\dedup-system-splink\outputs\threshold_comparison_proper.json"
with open(output_path, "w") as f:
    json.dump({"results": results}, f, indent=2)
print(f"Results saved to {output_path}")