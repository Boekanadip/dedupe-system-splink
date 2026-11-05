import pandas as pd
import warnings
from src.splink_model import train_and_predict
from create_stratified_train import create_stratified_training_df

warnings.filterwarnings('always')

# Load data - 5.000 record
df = pd.read_parquet('data/processed/crm_standardized.parquet').head(5000)

# Buat training set stratified dengan lebih banyak duplicate pattern
train_df = create_stratified_training_df(
    df,
    target_size=5000,
    email_frac=0.35,
    phone_frac=0.18,
    conflict_frac=0.12,
    random_state=42
)

COLS = ['first_name_std','last_name_std','email_std','phone_std','address_std','city_std','state_std','country_std','dob_std']

print('\n=== Mulai training dengan max_pairs=20.000 ===')

# Latih dengan training_df terpisah
pred, linker = train_and_predict(
    df,                          # Data scoring: 5.000 record
    selected_columns=COLS,
    max_pairs=20_000,            # Target max_pairs
    training_df=train_df         # Training stratified
)

p = pred['match_probability']
w = pred['match_weight']

print('\n=== Hasil Training ===')
print(f'Rows: {len(pred)}')
print(f'Decisions: {pred.decision.value_counts().to_dict()}')
print(f'Review band: {int(((p>=0.35)&(p<0.84)).sum())}')
print(f'Weight range: {w.min():.4f} to {w.max():.4f}')

# Audit pasangan konflik
same_email = pred['email_std_l'].eq(pred['email_std_r'])
same_phone = pred['phone_std_l'].eq(pred['phone_std_r'])
same_first = pred['first_name_std_l'].eq(pred['first_name_std_r'])
diff_last = pred['last_name_std_l'].ne(pred['last_name_std_r'])

mask_conflict = same_email & same_phone & same_first & diff_last
conflict_pairs = pred[mask_conflict]

print(f'\n=== Pasangan Konflik: email+sama + phone+sama + first sama + last berbeda ===')
print(f'Jumlah: {len(conflict_pairs)}')
if len(conflict_pairs) > 0:
    cols_show = ['record_id_l','record_id_r','match_weight','match_probability','decision','business_rule']
    print(conflict_pairs[cols_show].head(10).to_string(index=False))

# Audit email sama + phone berbeda + nama conflicts
mask_email_only = same_email & (~same_phone) & same_first & diff_last
email_only = pred[mask_email_only]

print(f'\n=== Pasangan: Email sama + phone BERBEDA + first sama + last berbeda ===')
print(f'Jumlah: {len(email_only)}')
if len(email_only) > 0:
    print(email_only[cols_show].head(10).to_string(index=False))

# Audit phone sama + email berbeda + nama conflicts
mask_phone_only = (~same_email) & same_phone & same_first & diff_last
phone_only = pred[mask_phone_only]

print(f'\n=== Pasangan: Phone sama + email BERBEDA + first sama + last berbeda ===')
print(f'Jumlah: {len(phone_only)}')
if len(phone_only) > 0:
    print(phone_only[cols_show].head(10).to_string(index=False))
