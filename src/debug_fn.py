"""Debug FN pairs: inspect their contact info."""
import pandas as pd

df = pd.read_parquet('data/processed/crm_standardized.parquet')
gold = pd.read_csv('data/labels/gold_labels.csv')
pred = pd.read_parquet('outputs/splink_predictions.parquet')

# Get FN pairs (match but prob < 0.10)
fn = pred[(pred['gold_label'] == 'match') & (pred['match_probability'] < 0.10)]
fn_ids = set(fn['record_id_l'].tolist() + fn['record_id_r'].tolist())
fn_df = df[df['record_id'].isin(fn_ids)]

print('FN record stats:')
print(f'FN records: {len(fn_ids)}')
print(f'FN records with email_std: {fn_df["email_std"].notna().sum()}')
print(f'FN records with phone_std: {fn_df["phone_std"].notna().sum()}')
print(f'FN records with email + phone: {((fn_df["email_std"].notna()) & (fn_df["phone_std"].notna())).sum()}')
print()
print('FN record sample (email, phone):')
for rid in list(fn_ids)[:10]:
    r = fn_df[fn_df['record_id'] == rid].iloc[0]
    print(f'{rid}: email={r["email_std"]}, phone={r["phone_std"]}')

print()
print('FN pairs (sample 5):')
print(fn[['record_id_l', 'record_id_r', 'match_probability']].head())
