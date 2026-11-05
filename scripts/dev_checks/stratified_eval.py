import pandas as pd
from src.splink_model import train_and_predict

DATA = 'data/processed/crm_standardized.parquet'
COLS = ['first_name_std','last_name_std','email_std','phone_std','address_std','city_std','state_std','country_std','dob_std']

df = pd.read_parquet(DATA).head(2000)

print('=== Step 1: Analyze duplicate patterns in full 2000 record subset ===')
dup_email = df[df.duplicated(subset='email_std', keep=False)]
dup_phone = df[df.duplicated(subset='phone_std', keep=False)]
dup_both = df[df.duplicated(subset=['email_std','phone_std'], keep=False)]

print(f'Rows with duplicate email_std: {len(dup_email)}')
print(f'Rows with duplicate phone_std: {len(dup_phone)}')
print(f'Rows with duplicate email+phone: {len(dup_both)}')

print()
print('=== Duplicate email+phone groups ===')
for g, idx in dup_both.groupby(['email_std','phone_std']).groups.items():
    subset = dup_both.loc[idx]
    print(f"\nEmail: {str(g[0])[:35]}... Phone: {str(g[1])[:10]}...")
    print(f"  Count: {len(subset)}")
    for _, r in subset.iterrows():
        print(f"  first={r['first_name_std']}, last={r['last_name_std']}, dob={r['dob_std']}")

print()
print('=== Step 2: Build stratified subset ===')
# Take all rows involved in duplicate email OR phone
strat_rows = set()

# Add duplicate email rows
for _, r in dup_email.iterrows():
    strat_rows.add(r['record_id'])

# Add duplicate phone rows
for _, r in dup_phone.iterrows():
    strat_rows.add(r['record_id'])

# Add some random non-duplicate rows for balance
non_dup = df[~df['record_id'].isin(strat_rows)].sample(n=min(500, len(df)-len(strat_rows)), random_state=42)
for _, r in non_dup.iterrows():
    strat_rows.add(r['record_id'])

strat_df = df[df['record_id'].isin(strat_rows)].copy()
print(f'Stratified subset size: {len(strat_df)}')
print(f'Of which duplicate email: {len(strat_df[strat_df.duplicated(subset="email_std", keep=False)])}')
print(f'Of which duplicate phone: {len(strat_df[strat_df.duplicated(subset="phone_std", keep=False)])}')
print(f'Of which duplicate email+phone: {len(strat_df[strat_df.duplicated(subset=["email_std","phone_std"], keep=False)])}')

print()
print('=== Step 3: Run train_and_predict on stratified subset ===')
pred, _ = train_and_predict(
    strat_df, verbose=False, selected_columns=COLS, max_pairs=200
)

p = pred['match_probability']
w = pred['match_weight']
LOW, HIGH = 0.35, 0.84

print(f'Rows: {len(pred)}')
print(f'Decisions: {pred.decision.value_counts().to_dict()}')
print(f'Review band: {int(((p>=LOW)&(p<HIGH)).sum())}')
print(f'Weight range: {w.min():.4f} to {w.max():.4f}')
print()

# Audit: email same + phone same + name conflict
same_email = pred['email_std_l'].eq(pred['email_std_r'])
same_phone = pred['phone_std_l'].eq(pred['phone_std_r'])
same_first = pred['first_name_std_l'].eq(pred['first_name_std_r'])
diff_last = pred['last_name_std_l'].ne(pred['last_name_std_r'])
dob_diff_or_missing = pred['dob_std_l'].isna() | pred['dob_std_r'].isna() | pred['dob_std_l'].ne(pred['dob_std_r'])

mask_conflict = same_email & same_phone & same_first & diff_last
conflict_pairs = pred[mask_conflict]
print(f'Email+sama+phone+sama+first sama+last berbeda: {len(conflict_pairs)}')
if len(conflict_pairs) > 0:
    print(conflict_pairs[['record_id_l','record_id_r','match_weight','match_probability','decision']].head(10).to_string(index=False))

print()
# Audit: email same + phone DIFFERENT + name conflict
mask_email_only = same_email & (~same_phone) & same_first & diff_last
email_only_pairs = pred[mask_email_only]
print(f'Email sama + phone BERBEDA + first sama + last berbeda: {len(email_only_pairs)}')
if len(email_only_pairs) > 0:
    print(email_only_pairs[['record_id_l','record_id_r','match_weight','match_probability','decision','business_rule']].head(10).to_string(index=False))
    print(f"Weight stats: min={email_only_pairs['match_weight'].min():.4f}, max={email_only_pairs['match_weight'].max():.4f}, mean={email_only_pairs['match_weight'].mean():.4f}")

print()
# Audit: phone same + email DIFFERENT + name conflict
mask_phone_only = (~same_email) & same_phone & same_first & diff_last
phone_only_pairs = pred[mask_phone_only]
print(f'Phone sama + email BERBEDA + first sama + last berbeda: {len(phone_only_pairs)}')
if len(phone_only_pairs) > 0:
    print(phone_only_pairs[['record_id_l','record_id_r','match_weight','match_probability','decision','business_rule']].head(10).to_string(index=False))