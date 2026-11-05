import pandas as pd

p = pd.read_parquet('outputs/splink_predictions.parquet')
mr = pd.read_parquet('outputs/master_customers.parquet')

# Ambil satu pasangan MATCH sebagai contoh
match_pair = p[p.decision == 'MATCH'].iloc[0]
rid_l = str(match_pair['record_id_l'])
rid_r = str(match_pair['record_id_r'])

print(f'=== PASANGAN: {rid_l} x {rid_r} ===')
print(f'Decision: {match_pair["decision"]}')
print(f'Match Probability: {match_pair["match_probability"]:.4f}')
print(f'Match Weight: {match_pair["match_weight"]:.4f}')
print()

# Dapatkan field standardized dari master - record kiri
for _, erow in mr.iterrows():
    ridx = str(erow['record_ids'])
    if rid_l in ridx:
        print(f'Record {rid_l} (Entity {erow["entity_id"]}):')
        print(f'  first_name_std: {erow.get("master_first_name_std", "N/A")}')
        print(f'  last_name_std:  {erow.get("master_last_name_std", "N/A")}')
        print(f'  email_std:      {erow.get("master_email_std", "N/A")}')
        print(f'  phone_std:      {erow.get("master_phone_std", "N/A")}')
        print(f'  city_std:       {erow.get("master_city_std", "N/A")}')
        print(f'  state_std:      {erow.get("master_state_std", "N/A")}')
        print(f'  address_std:    {erow.get("master_address_std", "N/A")}')
        print(f'  dob_std:        {erow.get("master_dob_std", "N/A")}')
        print()

# Record kanan
for _, erow in mr.iterrows():
    ridx = str(erow['record_ids'])
    if rid_r in ridx:
        print(f'Record {rid_r} (Entity {erow["entity_id"]}):')
        print(f'  first_name_std: {erow.get("master_first_name_std", "N/A")}')
        print(f'  last_name_std:  {erow.get("master_last_name_std", "N/A")}')
        print(f'  email_std:      {erow.get("master_email_std", "N/A")}')
        print(f'  phone_std:      {erow.get("master_phone_std", "N/A")}')
        print(f'  city_std:       {erow.get("master_city_std", "N/A")}')
        print(f'  state_std:      {erow.get("master_state_std", "N/A")}')
        print(f'  address_std:    {erow.get("master_address_std", "N/A")}')
        print(f'  dob_std:        {erow.get("master_dob_std", "N/A")}')
        print()
        break

# Bandingkan field per field
print('=== BANDINGAN FIELD PER FIELD ===')
field_map = {
    'first_name_std': 'first_name_std_l', 'first_name_std_r': 'first_name_std',
    'last_name_std': 'last_name_std_l', 'last_name_std_r': 'last_name_std',
    'email_std': 'email_std_l', 'email_std_r': 'email_std',
    'phone_std': 'phone_std_l', 'phone_std_r': 'phone_std',
    'city_std': 'city_std_l', 'city_std_r': 'city_std',
    'state_std': 'state_std_l', 'state_std_r': 'state_std',
    'address_std': 'address_std_l', 'address_std_r': 'address_std',
}

for raw_l, raw_r in field_map.items():
    # Read from master
    rec_l_val = None
    rec_r_val = None
    for _, erow in mr.iterrows():
        ridx = str(erow['record_ids'])
        if rid_l in ridx:
            rec_l_val = erow.get(raw_l.replace('_l',''), erow.get(raw_l.replace('_r',''), None))
        if rid_r in ridx:
            rec_r_val = erow.get(raw_r.replace('_l',''), erow.get(raw_r.replace('_r',''), None))
    match_flag = "SAMA" if (pd.notna(rec_l_val) and pd.notna(rec_r_val) and str(rec_l_val).lower() == str(rec_r_val).lower()) else "BERBEDA"
    print(f'{raw_l}: "{rec_l_val}" vs "{rec_r_val}" -> {match_flag}')