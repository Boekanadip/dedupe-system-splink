import pandas as pd
import numpy as np

np.random.seed(42)

n = 500  # 500 record

# Buat record-record dengan pola spesifik
data = []

# 1. Grup: email sama, phone BERBEDA, nama CONFLICT (target REVIEW)
n_review = 20
for i in range(n_review):
    email = f"review{i}@example.com"
    phone = 62811111111 + i  # phone berbeda
    # Nama: first_name sama tapi last_name berbeda
    first = f"user{i}"
    last_a = f"lastname_a_{i}"
    last_b = f"lastname_b_{i}"
    dob = "1990-01-01"
    alamat = f"jalan contoh no {i}"
    kota = "Jakarta"
    provinsi = "DKI Jakarta"
    kode_pos = "12345"
    negara = " Indonesia"
    phone_pre7 = str(phone)  # kolom pendukung blocking (ditypat string)
    
    # Record A
    data.append({
        'record_id': f'rev_a_{i}',
        'first_name_std': first,
        'last_name_std': last_a,
        'email_std': email,
        'phone_std': phone,
        'phone_pre7': phone,
        'address_std': alamat,
        'city_std': kota,
        'state_std': provinsi,
        'country_std': negara,
        'dob_std': dob
    })
    
    # Record B (sama email, phone berbeda, last name conflict)
    data.append({
        'record_id': f'rev_b_{i}',
        'first_name_std': first,
        'last_name_std': last_b,
        'email_std': email,
        'phone_std': 62822222222 + i,  # phone berbeda total
        'phone_pre7': str(62822222222 + i),
        'address_std': alamat,
        'city_std': kota,
        'state_std': provinsi,
        'country_std': negara,
        'dob_std': dob
    })

# 2. Grup: email sama, phone SAMA, nama CONFLICT (target MATCH)
n_match = 15
for i in range(n_match):
    email = f"match{i}@example.com"
    phone = 62811111111 + i  # phone sama
    first = f"user{i}"
    last_a = f"lastname_a_{i}"
    last_b = f"lastname_b_{i}"
    dob = "1990-01-01"
    phone_pre7 = str(phone)
    
    data.append({
        'record_id': f'mat_a_{i}',
        'first_name_std': first,
        'last_name_std': last_a,
        'email_std': email,
        'phone_std': phone,
        'phone_pre7': phone_pre7,
        'address_std': f"jalan match no {i}",
        'city_std': f"kota{ i }",
        'state_std': f"prov{i}",
        'country_std': "ID",
        'dob_std': dob
    })
    
    data.append({
        'record_id': f'mat_b_{i}',
        'first_name_std': first,
        'last_name_std': last_b,
        'email_std': email,
        'phone_std': phone,
        'phone_pre7': phone_pre7,
        'address_std': f"jalan match no {i}",
        'city_std': f"kota{ i }",
        'state_std': f"prov{i}",
        'country_std': "ID",
        'dob_std': dob
    })

# 3. Grup: email BERBEDA, phone BERBEDA, nama sama (target NON_MATCH)
n_nonmatch = 15
for i in range(n_nonmatch):
    email_a = f"diff{i}a@example.com"
    email_b = f"diff{i}b@example.com"
    phone_a = 62811111111 + i
    phone_b = 62822222222 + i
    first_a = f"user{i}"
    first_b = f"user{i+10}"
    last_same = f"lastname_same_{i}"
    dob = "1990-01-01"
    phone_pre7_a = str(phone_a)
    phone_pre7_b = str(phone_b)
    
    data.append({
        'record_id': f'nm_a_{i}',
        'first_name_std': first_a,
        'last_name_std': last_same,
        'email_std': email_a,
        'phone_std': phone_a,
        'phone_pre7': phone_pre7_a,
        'address_std': f"jalan diff no {i}a",
        'city_std': f"kota{ i }",
        'state_std': f"prov{i}",
        'country_std': "ID",
        'dob_std': dob
    })
    
    data.append({
        'record_id': f'nm_b_{i}',
        'first_name_std': first_b,
        'last_name_std': last_same,
        'email_std': email_b,
        'phone_std': phone_b,
        'phone_pre7': phone_pre7_b,
        'address_std': f"jalan diff no {i}b",
        'city_std': f"kota{ i }",
        'state_std': f"prov{i}",
        'country_std': "ID",
        'dob_std': dob
    })

# 4. Grup: email sama, phone sama, nama sama (target MATCH kuat)
n_strong_match = 10
for i in range(n_strong_match):
    email = f"strong{i}@example.com"
    phone = 62811111111 + i
    first = f"user{i}"
    last_same = f"lastname_same_{i}"
    dob = "1990-01-01"
    phone_pre7 = str(phone)
    
    data.append({
        'record_id': f'sma_{i}',
        'first_name_std': first,
        'last_name_std': last_same,
        'email_std': email,
        'phone_std': phone,
        'phone_pre7': phone_pre7,
        'address_std': f"jalan strong no {i}",
        'city_std': f"kota{ i }",
        'state_std': f"prov{i}",
        'country_std': "ID",
        'dob_std': dob
    })
    
    data.append({
        'record_id': f'sma2_{i}',
        'first_name_std': first,
        'last_name_std': last_same,
        'email_std': email,
        'phone_std': phone,
        'phone_pre7': phone_pre7,
        'address_std': f"jalan strong no {i}",
        'city_std': f"kota{ i }",
        'state_std': f"prov{i}",
        'country_std': "ID",
        'dob_std': dob
    })

df = pd.DataFrame(data)

# Tambah record acak untuk mencapai total 500+ record
existing_count = len(df)
needed = 500 - existing_count
if needed > 0:
    random_emails = [f"random{j}@example.com" for j in range(needed)]
    random_phones = [62811111111 + j for j in range(needed)]
    random_phone_pre7 = [str(62811111111 + j) for j in range(needed)]
    data_random = []
    for j in range(needed):
        data_random.append({
            'record_id': f'random_{j}',
            'first_name_std': f"random{j}",
            'last_name_std': f"lastname{ j }",
            'email_std': random_emails[j],
            'phone_std': random_phones[j],
            'phone_pre7': random_phone_pre7[j],
            'address_std': f"jalan random {j}",
            'city_std': f"kota{ j }",
            'state_std': f"prov{ j % 3 }",
            'country_std': "ID",
            'dob_std': "1990-01-01"
        })
    df = pd.concat([df, pd.DataFrame(data_random)], ignore_index=True)

# Pastikan kolom string benar-benar string untuk Splink
for c in ['phone_std', 'email_std', 'first_name_std', 'last_name_std',
          'address_std', 'city_std', 'state_std', 'country_std', 'dob_std']:
    df[c] = df[c].astype(str)

# Pastikan phone_pre7 adalah string (pyarrow kadang salah detect)
df['phone_pre7'] = df['phone_pre7'].astype(str)

# Tambah kolom phonetic_first_name dan phonetic_last_name untuk Splink name comparison
df['phonetic_first_name'] = df['first_name_std'].apply(lambda x: str(x)[:2] if pd.notna(x) and str(x).strip() else None)
df['phonetic_last_name'] = df['last_name_std'].apply(lambda x: str(x)[:2] if pd.notna(x) and str(x).strip() else None)

# Simpan
df.to_parquet('data/synthetic_review.parquet', index=False)
print(f"Data synthetic dibuat: {len(df)} record dengan kolom lengkap")
print(f"  - Grup REVIEW (email+sama+phonebeda+nama konflik): {n_review} pasangan")
print(f"  - Grup MATCH (email+sama+phone+sama+namabeda): {n_match} pasangan")
print(f"  - Grup NON_MATCH (emailbeda+phonebeda+namasama): {n_nonmatch} pasangan")
print(f"  - Grup STRONG_MATCH (email+sama+phone+sama+namasama): {n_strong_match} pasangan")

# Tampilkan contoh
print()
print("Contoh record REVIEW (email+sama, phonebeda, last conflict):")
review_df = df[df['record_id'].str.startswith('rev_')]
print(review_df[['record_id','email_std','phone_std','phone_pre7','first_name_std','last_name_std']].head(5).to_string(index=False))