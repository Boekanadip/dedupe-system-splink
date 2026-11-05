import warnings
warnings.filterwarnings('ignore')
import pandas as pd
from src.splink_model import train_and_predict

# Load data sintetis
df = pd.read_parquet('data/synthetic_review.parquet')

# Fokus eksperimen: nama + email + phone. Location/DOB sengaja dikeluarkan
# agar efek evidence contact dapat diisolasi.
COLS = ['first_name_std','last_name_std','email_std','phone_std']

# Test dengan max_pairs yang cukup (50.000 untuk 500 record)
pred, _ = train_and_predict(df, selected_columns=COLS, max_pairs=50000)

p = pred['match_probability']
w = pred['match_weight']

print('=== Ringkasan Prediksi ===')
print(f'Rows: {len(pred)}')
print(f'Decisions: {pred["decision"].value_counts().to_dict()}')
print(f'Review band (0.35 <= p < 0.84): {int(((p>=0.35)&(p<0.84)).sum())}')
print(f'Weight range: {float(w.min()):.4f} to {float(w.max()):.4f}')

print()
print('=== Audit: Pasangan REVIEW (target) ===')
# Cari pasangan dengan pola: email sama + phone BERBEDA + first sama + last DIFFERENT
same_email = pred['email_std_l'].eq(pred['email_std_r'])
same_first = pred['first_name_std_l'].eq(pred['first_name_std_r'])
diff_last = pred['last_name_std_l'].ne(pred['last_name_std_r'])
# phone harus DIFFERENT
phone_diff = pred['phone_std_l'].ne(pred['phone_std_r'])

mask_review = same_email & phone_diff & same_first & diff_last
review_pairs = pred[mask_review]
print(f'Pasangan: email+sama + phone BERBEDA + first sama + last berbeda')
print(f'Jumlah: {len(review_pairs)}')

if len(review_pairs) > 0:
    cols_show = ['record_id_l','record_id_r','match_weight','match_probability','decision']
    print(review_pairs[cols_show].head(10).to_string(index=False))
else:
    print('Tidak ditemukan pasangan dengan pola ini.')
    # Coba cari apa aja yang ada
    print()
    print('=== Cari pasangan email+sama saja ===')
    mask_email_same = same_email
    email_same_pairs = pred[mask_email_same]
    print(f'email sama: {len(email_same_pairs)} pasangan')
    if len(email_same_pairs) > 0:
        print(email_same_pairs[['record_id_l','record_id_r','match_weight','match_probability','decision']].head(5).to_string(index=False))
    
    print()
    print('=== Cari pasangan email+sama+phone sama ===')
    same_phone = pred['phone_std_l'].eq(pred['phone_std_r'])
    mask_both_same = same_email & same_phone
    both_same = pred[mask_both_same]
    print(f'email+sama+phone+sama: {len(both_same)} pasangan')
    if len(both_same) > 0:
        print(both_same[['record_id_l','record_id_r','match_weight','match_probability','decision']].head(5).to_string(index=False))