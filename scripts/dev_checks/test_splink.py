import pandas as pd

df = pd.read_parquet('data/processed/crm_standardized.parquet')
# Ensure record_id is string and first column
df['record_id'] = df['record_id'].astype(str)
# Move record_id to first column
df = df[['record_id'] + [c for c in df.columns if c != 'record_id']]
print('Shape:', df.shape)
print('First 2 rows:')
print(df.head(2))
print()
# Try to create a simple Splink Linker
import splink
print('Creating Linker...')
try:
    linker = splink.Linker(df)
    print('Success!')
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()
PYEOF