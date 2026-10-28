import pandas as pd

pred_df = pd.read_parquet(r"C:\Users\User\Downloads\dedup-system-splink\outputs\splink_predictions.parquet")
gold = pd.read_csv(r"C:\Users\User\Downloads\dedup-system-splink\data\labels\gold_labels.csv")

# Map pair_id
pred_df["pair_id"] = pred_df["record_id_l"].astype(str) + "_" + pred_df["record_id_r"].astype(str)
gold["pair_id"] = gold["record_id_l"].astype(str) + "_" + gold["record_id_r"].astype(str)

label_map = dict(zip(gold["pair_id"], gold["label"]))
pred_df["gold_label"] = pred_df["pair_id"].map(label_map)

# Find FN at threshold 0.9
threshold = 0.9
fn = pred_df[(pred_df["match_probability"] < threshold) & (pred_df["gold_label"] == "match")]
print(f"FN at threshold {threshold}: {len(fn)} pairs")
print()

# Show FN details
print("FN pairs (record_id_l, record_id_r, match_probability, gold_label):")
for _, row in fn.iterrows():
    print(f"  {row['record_id_l']} vs {row['record_id_r']} | prob={row['match_probability']:.4f} | gold={row['gold_label']}")

# Also check: at what threshold do we get recall >= 0.95?
print("\n\n--- Recall vs threshold analysis ---")
for t in [0.80, 0.81, 0.82, 0.83, 0.84, 0.85]:
    review_df = pred_df[pred_df["decision"] == "REVIEW"].copy()
    review_df["predicted_match"] = review_df["match_probability"] >= t
    
    # Include already MATCH pairs
    already_match = pred_df[pred_df["decision"] == "MATCH"]
    all_matched = pd.concat([already_match, review_df[predicted_match=True]])
    
    tp = int((all_matched["gold_label"] == "match").sum())
    fn_total = int((((~all_matched["predicted_match"] if 'predicted_match' in all_matched.columns else False)) & (all_matched["gold_label"] == "match")).sum())
    
    # Simpler: count total matched vs gold match
    total_matches_gold = int((pred_df["gold_label"] == "match").sum())
    recall = tp / total_matches_gold if total_matches_gold > 0 else 0
    
    print(f"Threshold {t}: Recall={recall:.4f} ({tp}/{total_matches_gold})")