import pandas as pd
from src.config import PROCESSED_DATA_PATH

df = pd.read_parquet(PROCESSED_DATA_PATH)
phone = df['phone_std'].dropna()
print('Phone count:', len(phone))
print()
print('Length distribution:')
print(phone.str.len().value_counts().sort_index().to_string())
print()
for prefix in ('001', '00', '1', '0'):
    print(f"starts with {prefix!r}: {phone.str.startswith(prefix).sum():,}")