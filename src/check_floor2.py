#!/usr/bin/env python3
"""Check M_ELSE_LEVEL_FLOOR effect on gold matches."""
import pandas as pd

p = pd.read_parquet('outputs/splink_predictions.parquet')
print('cols:', list(p.columns)[:30])
print('rows:', len(p))

g = pd.read_csv('data/labels/gold_labels.csv')
print('gold cols:', list(g.columns))

m = g.merge(p, on=['record_id_l','record_id_r'], how='left')
pos = m[m['label']=='match']
print('prob min:', pos['match_probability'].min())
print('5th perc:', pos['match_probability'].quantile(0.05))
print('Gold with prob<0.001:', (pos['match_probability'] < 0.001).sum())
print('Gold with prob<0.05:', (pos['match_probability'] < 0.05).sum())