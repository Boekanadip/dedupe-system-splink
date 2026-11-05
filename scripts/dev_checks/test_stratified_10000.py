import pandas as pd
from src.splink_model import train_and_predict
from create_stratified_train import create_stratified_training_df

DATA = 'data/processed/crm_standardized.parquet'
COLS = ['first_name_std','last_name_std','email_std','phone_std','address_std','city_std','state_std','country_std','dob_std']
full = pd.read_parquet(DATA)
train_source = full.head(10000).copy()
score_df = full.iloc[10000:20000].copy()
train_df = create_stratified_training_df(train_source, target_size=10000, email_frac=0.04, phone_frac=0.035, conflict_frac=0.01, random_state=42)
print('\n=== Training 10.000 records; scoring disjoint 10.000 records; max_pairs=50.000 ===')
pred, linker = train_and_predict(score_df, selected_columns=COLS, max_pairs=50000, training_df=train_df)
p = pred.match_probability
print('rows:', len(pred))
print('decisions:', pred.decision.value_counts().to_dict())
print('review_band:', int(((p >= .35) & (p < .84)).sum()))
print('weight_range:', float(pred.match_weight.min()), float(pred.match_weight.max()))
# Existing exact-field conflict audit on scored candidates
same_email = pred.email_std_l.eq(pred.email_std_r)
same_phone = pred.phone_std_l.eq(pred.phone_std_r)
name_conflict = pred.first_name_std_l.ne(pred.first_name_std_r) | pred.last_name_std_l.ne(pred.last_name_std_r)
for label, mask in [
    ('email_same_phone_diff_name_conflict', same_email & ~same_phone & name_conflict),
    ('phone_same_email_diff_name_conflict', same_phone & ~same_email & name_conflict),
    ('email_same_phone_same_name_conflict', same_email & same_phone & name_conflict),
]:
    x = pred[mask]
    print(label, len(x))
    if len(x): print(x[['record_id_l','record_id_r','match_weight','match_probability','decision']].head(5).to_string(index=False))
