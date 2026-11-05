import pandas as pd

p = pd.read_parquet('outputs/splink_predictions.parquet')
mr = pd.read_parquet('outputs/master_customers.parquet')

# Ambil satu pasangan NON_MATCH dengan prob tinggi
non_pair = p[(p.decision == 'NON_MATCH') & (p.match_probability > 0.5)].iloc[0]
rid_l = str(non_pair['record_id_l'])
rid_r = str(non_pair['record_id_r'])

print(f'=== PASANGAN: {rid_l} x {rid_r} ===')
print(f'Decision: {non_pair["decision"]}')
print(f'Match Probability: {non_pair["match_probability"]:.6f}')
print(f'Match Weight: {non_pair["match_weight"]:.4f}')
print(f'Business Rule: {non_pair["business_rule"]}')
print()

# Dapatkan field dari master
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
compare_fields = [
    'first_name_std', 'last_name_std', 'email_std', 
    'phone_std', 'city_std', 'state_std', 'address_std'
]
for cf in compare_fields:
    # Baca dari master kiri
    val_l = None
    val_r = None
    for _, erow in mr.iterrows():
        ridx = str(erow['record_ids'])
        if rid_l in ridx:
            val_l = erow.get(f'master_{cf}_l', erow.get(f'master_{cf}', None))
        if rid_r in ridx:
            val_r = erow.get(f'master_{cf}_r', erow.get(f'master_{cf}', None))
    
    # Normalisasi untuk perbandingan
    str_l = str(val_l).lower().strip() if pd.notna(val_l) else "NaN"
    str_r = str(val_r).lower().strip() if pd.notna(val_r) else "NaN"
    sama = "SAMA" if str_l == str_r and str_l != "nan" else "BERBEDA"
    print(f'{cf}: "{str_l}" vs "{str_r}" -> {sama}')