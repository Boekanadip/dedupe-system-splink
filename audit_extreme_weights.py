import pandas as pd
from src.splink_model import train_and_predict

DATA = 'data/processed/crm_standardized.parquet'
COLS = ['first_name_std','last_name_std','email_std','phone_std','address_std','city_std','state_std','country_std','dob_std']
df = pd.read_parquet(DATA).head(2000)
dup_email = df[df.duplicated('email_std', keep=False)]
dup_phone = df[df.duplicated('phone_std', keep=False)]
ids = set(dup_email.record_id) | set(dup_phone.record_id)
extra = df[~df.record_id.isin(ids)].sample(n=500, random_state=42)
subset = df[df.record_id.isin(ids | set(extra.record_id))]
pred, _ = train_and_predict(subset, verbose=False, selected_columns=COLS, max_pairs=200)
print('rows', len(pred), 'range', pred.match_weight.min(), pred.match_weight.max())
print('decisions', pred.decision.value_counts().to_dict())
print('columns', list(pred.columns))
for label, frame in [('lowest', pred.nsmallest(10, 'match_weight')), ('highest', pred.nlargest(10, 'match_weight'))]:
    print('\n===', label, '===')
    cols = [c for c in pred.columns if c.startswith('gamma_') or c.startswith('bf_')]
    cols += ['record_id_l','record_id_r','match_weight','match_probability','decision']
    print(frame[[c for c in cols if c in frame]].to_string(index=False))
