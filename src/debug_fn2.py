"""Debug FN pairs: inspect their contact comparison details."""
import pandas as pd
import json

df = pd.read_parquet('data/processed/crm_standardized.parquet')
pred = pd.read_parquet('outputs/splink_predictions.parquet')

# Get FN pairs (match but prob < 0.10)
fn = pred[(pred['gold_label'] == 'match') & (pred['match_probability'] < 0.10)]
fn_ids = set(fn['record_id_l'].tolist() + fn['record_id_r'].tolist())

# Get the blocking keys for these records
block_keys = {}
for rid in fn_ids:
    r = df[df['record_id'] == rid]
    if len(r) > 0:
        r = r.iloc[0]
        key = f"{r['email_std']}|{r['phone_std']}|{r['last_name_std']}|{r['first_name_std']}"
        block_keys[rid] = key

# Print FN pairs with their details
print('FN pairs analysis (sample 10):')
fn_sample = fn[['record_id_l', 'record_id_r', 'match_probability']].head(10)
for _, row in fn_sample.iterrows():
    rid_l = row['record_id_l']
    rid_r = row['record_id_r']
    prob = row['match_probability']
    
    rl = df[df['record_id'] == rid_l].iloc[0]
    rr = df[df['record_id'] == rid_r].iloc[0]
    
    print(f"\nPair: {rid_l} vs {rid_r}")
    print(f"  Prob: {prob:.6f}")
    print(f"  Email L: {rl['email_std']}")
    print(f"  Email R: {rr['email_std']}")
    print(f"  Phone L: {rl['phone_std']}")
    print(f"  Phone R: {rr['phone_std']}")
    print(f"  Name L: {rl['last_name_std']} {rl['first_name_std']}")
    print(f"  Name R: {rr['last_name_std']} {rr['first_name_std']}")
    
    # Jaro-Winkler similarity
    from rapidfeller import jaro_winkler_similarity
    if rl['phone_std'] and rr['phone_std']:
        pw = jaro_winkler_similarity(rl['phone_std'], rr['phone_std'])
        print(f"  Phone JW: {pw:.4f}")
    if rl['email_std'] and rr['email_std']:
        ew = jaro_winkler_similarity(rl['email_std'], rr['email_std'])
        print(f"  Email JW: {ew:.4f}")