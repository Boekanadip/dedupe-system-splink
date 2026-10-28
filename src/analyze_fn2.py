import pandas as pd

preds = pd.read_parquet('outputs/splink_predictions.parquet')
labels = pd.read_csv('data/labels/gold_labels.csv')

# Positive pairs in labels
pos_pairs = labels[labels['label'] == 'match']

# Merge to find which positive pairs have low probability
merged = preds.merge(pos_pairs[['record_id_l', 'record_id_r']], 
                     on=['record_id_l', 'record_id_r'], how='inner')
print('Positive pairs in preds:', len(merged))
print('At prob < 0.9:', (merged['match_probability'] < 0.9).sum())
print('At prob < 0.95:', (merged['match_probability'] < 0.95).sum())

# Sample FN
fn = merged[merged['match_probability'] < 0.9]
print(f'\nFN sample (n=10):')
for _, r in fn.head(10).iterrows():
    prob = r['match_probability']
    rid_l = r['record_id_l']
    rid_r = r['record_id_r']
    print(f'prob={prob:.4f} | {rid_l} × {rid_r}')

# Check field agreements
print('\n=== Field agreements for FN sample ===')
for _, r in fn.head(5).iterrows():
    print(f'prob={r["match_probability"]:.4f} | {r["record_id_l"]} × {r["record_id_r"]}')
    # Check the standardized field values
    print(f'  first_name_std_l={r["first_name_std_l"]}, first_name_std_r={r["first_name_std_r"]}')
    print(f'  last_name_std_l={r["last_name_std_l"]}, last_name_std_r={r["last_name_std_r"]}')
    print(f'  email_std_l={r["email_std_l"]}, email_std_r={r["email_std_r"]}')
    print(f'  phone_std_l={r["phone_std_l"]}, phone_std_r={r["phone_std_r"]}')
    print(f'  dob_std_l={r["dob_std_l"]}, dob_std_r={r["dob_std_r"]}')
    print(f'  city_std_l={r["city_std_l"]}, city_std_r={r["city_std_r"]}')