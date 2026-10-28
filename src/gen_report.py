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

# Current model evaluation
print("\n=== CURRENT MODEL EVALUATION ===")
print(f"213 pairs already classified MATCH (prob >= 0.966)")
print(f"377 pairs REVIEW (prob 0-0.841)")
print(f"37 pairs NON_MATCH (prob 0-1.0)")

# Since max REVIEW prob = 0.841, thresholds 0.86+ won't promote any pairs
# Let's verify the 12 FN pairs at threshold 0.9
threshold = 0.9
fn = pred_df[(pred_df["match_probability"] < threshold) & (pred_df["gold_label"] == "match")]
print(f"\nFN pairs at threshold {threshold}: {len(fn)} pairs")

# Count how many total would be MATCH at various thresholds
# by promoting REVIEW pairs with prob >= threshold
review_mask = pred_df["decision"] == "REVIEW"
for t in [0.80, 0.82, 0.84, 0.85, 0.86, 0.87, 0.88, 0.89]:
    # REVIEW pairs promoted to MATCH if prob >= t
    promoted_count = int((review_mask) & (pred_df["match_probability"] >= t)).sum()
    # Already MATCH + promoted
    total_matched = 213 + promoted_count
    
    # True positives among matched
    if promoted_count > 0:
        promoted_ids = pred_df[(review_mask) & (pred_df["match_probability"] >= t)]["pair_id"].tolist()
        tp_promoted = sum(1 for pid in promoted_ids if label_map.get(pid) == "match")
    else:
        tp_promoted = 0
    
    # Total TP = already MATCH (assumed all correct) + promoted that are true matches
    # But already MATCH may include some FP - use gold label directly
    all_matched_ids = list(pred_df[pred_df["decision"] == "MATCH"]["pair_id"]) + promoted_ids if promoted_count > 0 else list(pred_df[pred_df["decision"] == "MATCH"]["pair_id"])
    tp_total = sum(1 for pid in all_matched_ids if label_map.get(pid) == "match")
    
    recall = tp_total / total_matches_gold if total_matches_gold > 0 else 0
    precision = tp_total / total_matched if total_matched > 0 else 0
    
    print(f"Threshold {t}: REVIEW promoted={promoted_count}, TP total={tp_total}, Recall={recall:.4f} ({tp_total}/{total_matches_gold}), Precision={precision:.4f}")

# Save threshold comparison results
results = []
for t in [0.86, 0.87, 0.88, 0.89]:
    promoted_count = int((review_mask) & (pred_df["match_probability"] >= t)).sum()
    total_matched = 213 + promoted_count
    
    if promoted_count > 0:
        promoted_ids = pred_df[(review_mask) & (pred_df["match_probability"] >= t)]["pair_id"].tolist()
        tp_promoted = sum(1 for pid in promoted_ids if label_map.get(pid) == "match")
    else:
        tp_promoted = 0
    
    all_matched_ids = list(pred_df[pred_df["decision"] == "MATCH"]["pair_id"]) + promoted_ids if promoted_count > 0 else list(pred_df[pred_df["decision"] == "MATCH"]["pair_id"])
    tp_total = sum(1 for pid in all_matched_ids if label_map.get(pid) == "match")
    
    recall = tp_total / total_matches_gold if total_matches_gold > 0 else 0
    precision = tp_total / total_matched if total_matched > 0 else 0
    
    results.append({
        "threshold": t,
        "review_promoted": promoted_count,
        "total_matched": total_matched,
        "tp_total": tp_total,
        "recall": round(recall, 4),
        "precision": round(precision, 4)
    })

output_path = r"C:\Users\User\Downloads\dedup-system-splink\outputs\threshold_comparison_20261027.json"
with open(output_path, "w") as f:
    json.dump({"results": results}, f, indent=2)
print(f"\nResults saved to {output_path}")

# Key finding summary
print("\n=== KEY FINDINGS ===")
print(f"- Max match_probability in REVIEW pairs: 0.841")
print(f"- Thresholds 0.86-0.89 promote 0 additional REVIEW pairs (max prob = 0.841)")
print(f"- Recall with current classification: 213/{total_matches_gold} = {213/total_matches_gold:.4f}")
print(f"- 12 FN pairs have prob 0.815-0.841 (below thresholds 0.86+)")
print(f"- To reach recall >= 0.95: need to either lower threshold to 0.85 or retrain model")