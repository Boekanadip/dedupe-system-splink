import pandas as pd
import splink

# 1. Cek predictions
pred = pd.read_parquet('outputs/splink_predictions.parquet')
print('=== 1. PREDICTIONS ===')
print(f'Total: {len(pred)}')
print(f'Decision: {pred["decision"].value_counts().to_dict()}')
print(f'>0.95 MATCH: {(pred["match_probability"] > 0.95).sum()}')
print(f'<0.01 NON_MATCH: {(pred["match_probability"] < 0.01).sum()}')
print(f'0.01-0.95 REVIEW: {((pred["match_probability"] > 0.01) & (pred["match_probability"] < 0.95)).sum()}')

# 2. Cek blocking rules
print('\n=== 2. BLOCKING RULES ===')
import sys
sys.path.insert(0, 'src')
from config import DEFAULT_BENCHMARK_RULES
for name, cols in DEFAULT_BENCHMARK_RULES:
    print(f'  {name}: {cols}')

# 3. Cek field _std di parquet
print('\n=== 3. PARQUET COLUMNS (standarisasi) ===')
std_cols = [c for c in pred.columns if '_std' in c]
print(f'Total kolom _std: {len(std_cols)}')
sample_std = std_cols[:10]
print(f'Sample: {sample_std}')

# 4. Cek sample row
print('\n=== 4. SAMPLE ROW ===')
sample = pred.iloc[0]
print(f'record_id_l: {sample["record_id_l"]}')
print(f'record_id_r: {sample["record_id_r"]}')
print(f'match_probability: {sample["match_probability"]}')
print(f'decision: {sample["decision"]}')
print(f'email_std_l: {sample["email_std_l"]}')
print(f'phone_pre7_l: {sample["phone_pre7_l"]}')