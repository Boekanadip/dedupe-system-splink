#!/usr/bin/env python3
"""Threshold sweep incl. 0.4 on the current gold set."""
import pandas as pd

p = pd.read_parquet('outputs/splink_predictions.parquet')
g = pd.read_csv('data/labels/gold_labels.csv')
m = g.merge(p, on=['record_id_l', 'record_id_r'], how='left', suffixes=('_g', '_p'))

pos = m[m['label'] == 'match']
neg = m[m['label'] == 'no_match']
print(f"positives={len(pos)} negatives={len(neg)}")

for t in [0.9, 0.5, 0.4, 0.3, 0.1]:
    tp = int((pos['match_probability_p'] >= t).sum())
    fn = int((pos['match_probability_p'] < t).sum())
    fp = int((neg['match_probability_p'] >= t).sum())
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / len(pos) if len(pos) else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    print(f'thr {t}: TP={tp} FN={fn} FP={fp} Prec={prec:.4f} Rec={rec:.4f} F1={f1:.4f}')
