import pandas as pd
p = pd.read_parquet('outputs/splink_predictions.parquet')
mr = pd.read_parquet('outputs/master_customers.parquet')
high_non = p[(p.decision=='NON_MATCH') & (p.match_probability > 0.5)].head(6)

for _, row in high_non.iterrows():
    rid_l = str(row['record_id_l'])
    rid_r = str(row['record_id_r'])
    print(f'=== Pair: {rid_l} x {rid_r} ===')
    print(f'Prob: {row.match_probability}, Weight: {row.match_weight}')
    print(f'Business rule: {row.business_rule}')
    
    # Find and show field values for both records
    for _, erow in mr.iterrows():
        ridx = str(erow['record_ids'])
        if rid_l in ridx:
            print(f'  Record {rid_l}:')
            for c in ['master_first_name_std','master_last_name_std','master_email_std','master_city_std','master_state_std']:
                if c in erow:
                    print(f'    {c}: {erow[c]}')
        rid_r_idx = str(erow['record_ids'])
        if rid_r in rid_r_idx:
            print(f'  Record {rid_r}:')
            for c in ['master_first_name_std','master_last_name_std','master_email_std','master_city_std','master_state_std']:
                if c in erow:
                    print(f'    {c}: {erow[c]}')
    print()