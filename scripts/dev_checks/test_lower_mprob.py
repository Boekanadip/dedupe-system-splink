import pandas as pd
from src.splink_model import train_and_predict

df = pd.read_parquet('data/processed/crm_standardized.parquet').head(2000)
COLS = ['first_name_std','last_name_std','email_std','phone_std','address_std','city_std','state_std','country_std','dob_std']

pred, _ = train_and_predict(df, verbose=False, selected_columns=COLS, max_pairs=200)
p = pred['match_probability']
w = pred['match_weight']

print('rows:', len(pred))
print('decisions:', pred['decision'].value_counts().to_dict())
print('review_band:', int(((p>=0.35)&(p<0.84)).sum()))
print('weight range:', w.min(), 'to', w.max())
print()
# Cari pasangan email sama + phone sama + nama berbeda
same_email = pred['email_std_l'].eq(pred['email_std_r'])
same_phone = pred['phone_std_l'].eq(pred['phone_std_r'])
same_first = pred['first_name_std_l'].eq(pred['first_name_std_r'])
diff_last = pred['last_name_std_l'].ne(pred['last_name_std_r'])

mask = same_email & same_phone & same_first & diff_last
cand = pred[mask]
print('email+sama+phone+sama+first sama+last berbeda:', len(cand))
if len(cand) > 0:
    print(cand[['record_id_l','record_id_r','match_weight','match_probability','decision']].head(5).to_string(index=False))