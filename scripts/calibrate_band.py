"""Prioritas 2: kalibrasi pita 0.35-0.84 (observed match rate per bin 0.05).

Read-only. Tidak menulis DB, tidak mengubah model/threshold.

Sumber label:
  500  -> outputs/experiments/db_eval_pairs_500_enriched.csv (gold_label)
  300  -> outputs/experiments/production_audit_300_labeled.csv (review_label),
          probabilitas di-merge dari outputs/splink_predictions.parquet.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.config import active_path, predictions_path

OUT = Path('outputs/experiments')
MATCH = 0.84
REVIEW = 0.35
BIN = 0.05


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def bin_label(p: float) -> str:
    if p < REVIEW:
        return '<0.35'
    if p >= MATCH:
        return '>=0.84'
    lo = math.floor(p / BIN) * BIN
    lo = max(lo, REVIEW)
    return f'{lo:.2f}-{lo + BIN:.2f}'


def summarise(df: pd.DataFrame, prob_col: str, label_col: str, name: str) -> dict:
    d = df[[prob_col, label_col]].copy()
    d.columns = ['p', 'label']
    d = d.dropna(subset=['p'])
    d['label'] = d['label'].astype(str).str.strip().str.lower()
    d = d[d['label'].isin(['match', 'non_match'])]
    d['bin'] = d['p'].map(bin_label)

    rows = []
    order = ['<0.35'] + [
        f'{REVIEW + i * BIN:.2f}-{REVIEW + (i + 1) * BIN:.2f}'
        for i in range(int(round((MATCH - REVIEW) / BIN)))
    ] + ['>=0.84']
    for b in order:
        sub = d[d['bin'] == b]
        n = len(sub)
        k = int((sub['label'] == 'match').sum())
        lo, hi = wilson(k, n)
        rows.append({
            'bin': b,
            'pairs': n,
            'observed_match_rate': round(k / n, 4) if n else None,
            'mean_probability': round(float(sub['p'].mean()), 4) if n else None,
            'calibration_gap': round(float(sub['p'].mean()) - k / n, 4) if n else None,
            'ci95': [lo, hi] if n else None,
        })

    band = d[(d.p >= REVIEW) & (d.p < MATCH)]
    distinct = sorted(band.p.round(6).unique().tolist())
    return {
        'source': name,
        'pairs_used': int(len(d)),
        'dropped_unsure_or_missing': int(len(df) - len(d)),
        'bins': rows,
        'review_band': {
            'pairs': int(len(band)),
            'observed_match_rate': round(float((band.label == 'match').mean()), 4) if len(band) else None,
            'distinct_probabilities': distinct,
            'point_mass_note': (
                'band REVIEW berupa satu titik massa, bukan pita kontinu'
                if len(distinct) <= 1 else
                'band REVIEW tersebar di beberapa nilai probabilitas'
            ),
        },
        'monotonic': all(
            (a['observed_match_rate'] or 0) <= (b['observed_match_rate'] or 0)
            for a, b in zip(
                [r for r in rows if r['pairs']],
                [r for r in rows if r['pairs']][1:],
            )
        ),
    }


def main() -> None:
    report: dict = {'thresholds': {'review': REVIEW, 'match': MATCH}, 'bin_width': BIN}

    path500 = OUT / 'db_eval_pairs_500_enriched.csv'
    if path500.exists():
        d = pd.read_csv(path500)
        report['labels_500'] = summarise(d, 'match_probability', 'gold_label', 'db_eval_pairs_500_enriched')

    path300 = OUT / 'production_audit_300_labeled.csv'
    if path300.exists():
        d = pd.read_csv(path300)
        preds = pd.read_parquet(active_path(predictions_path(full=True)))
        preds = preds.assign(
            record_id_l=preds.record_id_l.astype(str),
            record_id_r=preds.record_id_r.astype(str),
        )
        probs = preds.set_index(['record_id_l', 'record_id_r']).match_probability
        keys = list(zip(d.record_id_l.astype(str), d.record_id_r.astype(str)))
        d['match_probability'] = [probs.get(k) for k in keys]
        report['labels_300'] = summarise(d, 'match_probability', 'review_label', 'production_audit_300_labeled')
        report['labels_300']['probability_merge_missing'] = int(d.match_probability.isna().sum())

    report['read_only'] = True
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'calibration_band_035_084.json'
    path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
