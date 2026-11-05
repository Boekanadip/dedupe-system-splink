import warnings
warnings.filterwarnings('ignore')

import pandas as pd
from src.splink_model import train_and_predict

DATA = 'data/synthetic_review.parquet'
COLS = ['first_name_std', 'last_name_std', 'email_std', 'phone_std']

df = pd.read_parquet(DATA).copy()
rows = []

# Tambahkan lima pola eksplisit; setiap pola 20 pasangan.
for i in range(20):
    patterns = [
        ('email_same_phone_diff_name_diff', f'p1_{i}@x.test', f'628700{i:05d}', f'628800{i:05d}', 'Alpha', f'LastA{i}', f'LastB{i}'),
        ('email_diff_phone_same_name_diff', f'p2a_{i}@x.test', f'628900{i:05d}', f'628900{i:05d}', 'Bravo', f'LastA{i}', f'LastB{i}'),
        ('email_same_phone_diff_name_same', f'p3_{i}@x.test', f'629000{i:05d}', f'629100{i:05d}', 'Charlie', f'Last{i}', f'Last{i}'),
        ('email_diff_phone_same_name_same', f'p4a_{i}@x.test', f'629200{i:05d}', f'629200{i:05d}', 'Delta', f'Last{i}', f'Last{i}'),
        ('email_diff_phone_diff_name_same', f'p5a_{i}@x.test', f'629300{i:05d}', f'629400{i:05d}', 'Echo', f'Last{i}', f'Last{i}'),
    ]
    for label, email_a, phone_a, phone_b, first, last_a, last_b in patterns:
        email_b = email_a.replace('@x.test', 'b@x.test') if label.startswith('email_diff') else email_a
        for side, email, phone, last in [('a', email_a, phone_a, last_a), ('b', email_b, phone_b, last_b)]:
            rows.append({
                'record_id': f'{label}_{i}_{side}',
                'first_name_std': first,
                'last_name_std': last,
                'email_std': str(email),
                'phone_std': str(phone),
                'phone_pre7': str(phone),
                'phonetic_first_name': first[:2],
                'phonetic_last_name': last[:2],
            })

patterns_df = pd.DataFrame(rows)
for c in ['address_std', 'city_std', 'state_std', 'country_std', 'dob_std']:
    patterns_df[c] = None

df = pd.concat([df, patterns_df], ignore_index=True)
for c in ['phone_std', 'phone_pre7', 'email_std', 'first_name_std', 'last_name_std']:
    df[c] = df[c].astype(str)

pred, _ = train_and_predict(df, selected_columns=COLS, max_pairs=50000)

print('=== Ringkasan ===')
print('candidate_rows:', len(pred))
print('decisions:', pred['decision'].value_counts().to_dict())
print('review_rows:', int(((pred.match_probability >= .35) & (pred.match_probability < .84)).sum()))

checks = {
    'email sama + phone BERBEDA + nama konflik': ('p1_', True, True),
    'email BERBEDA + phone sama + nama konflik': ('p2_', False, True),
    'email sama + phone BERBEDA + nama sama': ('p3_', True, False),
    'email BERBEDA + phone sama + nama sama': ('p4_', False, False),
    'email BERBEDA + phone BERBEDA + nama sama': ('p5_', False, False),
}

print('\n=== Audit pola ===')
for label, (prefix, email_same_expected, name_conflict_expected) in checks.items():
    x = pred[pred.record_id_l.str.startswith(prefix) & pred.record_id_r.str.startswith(prefix)].copy()
    if not len(x):
        print(label, '| candidate: 0 | tidak masuk blocking')
        continue
    same_email = x.email_std_l.eq(x.email_std_r)
    same_phone = x.phone_std_l.eq(x.phone_std_r)
    same_name = x.first_name_std_l.eq(x.first_name_std_r) & x.last_name_std_l.eq(x.last_name_std_r)
    print(label, '| candidate:', len(x), '| decisions:', x.decision.value_counts().to_dict(), '| weights:', (round(x.match_weight.min(), 3), round(x.match_weight.max(), 3)), '| name_same:', int(same_name.sum()), '| email_same:', int(same_email.sum()), '| phone_same:', int(same_phone.sum()))
    print(x[['record_id_l', 'record_id_r', 'match_weight', 'match_probability', 'decision']].head(2).to_string(index=False))
