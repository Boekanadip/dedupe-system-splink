#!/usr/bin/env python3
"""Check M_ELSE_LEVEL_FLOOR effect on gold matches."""
import pandas as pd
from src.config import M_ELSE_LEVEL_FLOOR_BY_FIELD, m_else_floor_for

# Cek distribusi match_probability minimal gold yang di bawah 0.05
p = pd.read_parquet('outputs/splink_predictions.parquet')
g = pd.read_csv('data/labels/gold_labels.csv')
m = g.merge(p, on=['record_id_l','record_id_r'], how='left')

pos = m[m['label']=='match']
print(f'Total gold matches: {len(pos)}')
print(f'Gold match prob min: {pos["match_probability"].min()}')
print(f'Gold match prob 5th perc: {pos["match_probability"].quantile(0.05)}')

# Cek berapa gold prob < 0.001
print(f'Gold matches with prob < 0.001: {(pos["match_probability"] < 0.001).sum()}')
print(f'Gold matches with prob < 0.05: {(pos["match_probability"] < 0.05).sum()}')
print(f'Gold matches with prob < 0.5: {(pos["match_probability"] < 0.5).sum()}')

# Cek current floor
print(f'\\nCurrent dob_std floor: {m_else_floor_for("dob_std")}')
print(f'Current phone_std floor: {m_else_floor_for("phone_std")}')