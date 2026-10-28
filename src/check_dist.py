import pandas as pd

pred_df = pd.read_parquet(r"C:\Users\User\Downloads\dedup-system-splink\outputs\splink_predictions.parquet")

# Check distribution of match_probability by decision
print("Match probability distribution by decision:")
print(pred_df.groupby("decision")["match_probability"].describe().to_string())
print()

# Check REVIEW pairs specifically
review_df = pred_df[pred_df["decision"] == "REVIEW"].copy()
print(f"REVIEW pairs count: {len(review_df)}")
print(f"REVIEW match_probability range: {review_df['match_probability'].min():.4f} - {review_df['match_probability'].max():.4f}")
print(f"REVIEW match_probability mean: {review_df['match_probability'].mean():.4f}")
print()

# Check how many REVIEW pairs have prob >= 0.86
for t in [0.86, 0.87, 0.88, 0.89]:
    count = int((review_df['match_probability'] >= t).sum())
    print(f"REVIEW pairs with prob >= {t}: {count}/{len(review_df)} ({count/len(review_df)*100:.1f}%)")

# Check MATCH pairs
match_df = pred_df[pred_df["decision"] == "MATCH"].copy()
print(f"\nMATCH pairs count: {len(match_df)}")
print(f"MATCH match_probability range: {match_df['match_probability'].min():.4f} - {match_df['match_probability'].max():.4f}")

# Check NON_MATCH pairs
nonmatch_df = pred_df[pred_df["decision"] == "NON_MATCH"].copy()
print(f"\nNON_MATCH pairs count: {len(nonmatch_df)}")
print(f"NON_MATCH match_probability range: {nonmatch_df['match_probability'].min():.4f} - {nonmatch_df['match_probability'].max():.4f}")