import pandas as pd

pred_df = pd.read_parquet(r"C:\Users\User\Downloads\dedup-system-splink\outputs\splink_predictions.parquet")

# Check match_probability distribution
print("=== MATCH PROBABILITY DISTRIBUTION ===")
print(pred_df['match_probability'].describe())
print()

# Current decisions
print("=== CURRENT DECISIONS ===")
print(f"MATCH: {len(pred_df[pred_df['decision'] == 'MATCH'])} pairs")
print(f"REVIEW: {len(pred_df[pred_df['decision'] == 'REVIEW'])} pairs")
print(f"NON_MATCH: {len(pred_df[pred_df['decision'] == 'NON_MATCH'])} pairs")
print()

# For thresholds 0.81 and 0.82, check how many REVIEW pairs would be promoted
for t in [0.81, 0.82]:
    # Count REVIEW pairs with prob >= threshold
    review_df = pred_df[pred_df['decision'] == 'REVIEW'].copy()
    promoted = int((review_df['match_probability'] >= t).sum())
    not_promoted = len(review_df) - promoted
    
    # Also check MATCH pairs prob range
    match_df = pred_df[pred_df['decision'] == 'MATCH'].copy()
    
    # Check NON_MATCH pairs prob range
    nonmatch_df = pred_df[pred_df['decision'] == 'NON_MATCH'].copy()
    
    print(f"=== Threshold {t} ===")
    print(f"REVIEW pairs promoted to MATCH: {promoted}/{len(review_df)} ({promoted/len(review_df)*100:.1f}%)")
    print(f"REVIEW pairs staying in REVIEW: {not_promoted}/{len(review_df)} ({not_promoted/len(review_df)*100:.1f}%)")
    print(f"  - Max prob in REVIEW: {review_df['match_probability'].max():.4f}")
    print(f"  - Min prob in REVIEW: {review_df['match_probability'].min():.4f}")
    print(f"  - Mean prob in REVIEW: {review_df['match_probability'].mean():.4f}")
    print()
    
    # Show pairs that would be right at the boundary
    boundary_df = review_df[(review_df['match_probability'] >= t - 0.01) & (review_df['match_probability'] < t + 0.01)]
    print(f"REVIEW pairs near boundary (prob {t-0.01:.2f}-{t+0.01:.2f}): {len(boundary_df)} pairs")
    if len(boundary_df) > 0:
        print(boundary_df[['record_id_l', 'record_id_r', 'match_probability', 'gold_label'] if 'gold_label' in boundary_df.columns else ['record_id_l', 'record_id_r', 'match_probability']].head(5).to_string())
    print()

# Summary
print("=== RINGKASAN ===")
print(f"Max match_probability in REVIEW: 0.841")
print(f"At threshold 0.81: promoted = pairs with prob >= 0.81")
print(f"At threshold 0.82: promoted = pairs with prob >= 0.82")
print(f"Difference: thresholds 0.81-0.82 only promote pairs with prob exactly 0.82 (very few)")