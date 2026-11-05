import traceback
import pandas as pd
from splink import DuckDBAPI, Linker, SettingsCreator
from src.splink_model import build_dynamic_settings_from_columns

path = 'data/synthetic_review.parquet'
df = pd.read_parquet(path).head(500)
cols = ['first_name_std', 'last_name_std', 'email_std', 'phone_std']
settings = build_dynamic_settings_from_columns(cols)

needed = {'first_name_std','last_name_std','email_std','phone_std','address_std','city_std','state_std','dob_std','dob_year_std'}
print('rows:', len(df))
print('columns:', list(df.columns))
print('kolom hilang:', sorted(needed - set(df.columns)))
print('null rate:')
print(df[[c for c in sorted(needed) if c in df]].isna().mean().to_string())

for i, comp in enumerate(settings['comparisons']):
    name = comp.create_output_column_name()
    print(f'\n=== TEST comparison {i}: {name} ===')
    try:
        s = SettingsCreator(
            link_type='dedupe_only',
            unique_id_column_name='record_id',
            comparisons=[comp],
            blocking_rules_to_generate_predictions=[],
        )
        db = DuckDBAPI()
        table = db.register(df, table_name=f't_{i}_{name}')
        lk = Linker(table, s)
        lk.training.estimate_u_using_random_sampling(max_pairs=50_000, seed=1)
        print('OK')
    except Exception:
        print('FAIL')
        traceback.print_exc()
