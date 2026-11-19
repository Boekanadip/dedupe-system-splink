"""AC-N1 / AC-N2 / AC-N3: perilaku skor saat bukti dihapus pada pasangan negatif.

Read-only. Model tersimpan dipakai ulang, blocking diganti rule konstan
`l._pairkey = r._pairkey` supaya pasangan uji pasti dinilai.

Kelompok uji:
  NON_MATCH (P < 0.35)  -> AC-N1 (variants) dan AC-N3 (address)
  REVIEW (0.35<=P<0.84) -> AC-N2 (address), dari band 107 pasangan
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import pandas as pd

from src.config import PROCESSED_DATA_PATH, active_path, predictions_path
from model_diagnostics import build_frame, load_model, score_pairs

OUT = Path('outputs/experiments')
MATCH = 0.84
REVIEW = 0.35
TOL = 1e-9

VARIANTS = {
    'contacts_both': ['email_std', 'phone_std'],
    'name_both': ['first_name_std', 'last_name_std'],
    'address_and_dob': ['address_std', 'dob_std'],
}


def score_set(pairs, model, fields=None):
    if fields:
        pairs = [
            ({**left, **{f: None for f in fields}}, right) for left, right in pairs
        ]
    return score_pairs(build_frame(pairs), model)


def split_row(row, side):
    suffix = f'_{side}'
    return {c[: -len(suffix)]: row[c] for c in row if c.endswith(suffix)}


def verdict(passed, pairs):
    if not pairs:
        return 'UNTESTED'
    return 'PASS' if passed else 'FAIL'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--negatives', type=int, default=200)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()

    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    index = df.set_index(df.record_id.astype(str))
    known = set(index.index)

    preds = pd.read_parquet(active_path(predictions_path(full=True)))
    preds = preds.assign(
        l=preds.record_id_l.astype(str), r=preds.record_id_r.astype(str)
    )
    preds = preds[preds.l.isin(known) & preds.r.isin(known) & preds.l.ne(preds.r)]
    neg_pool = preds[preds.decision.eq('NON_MATCH')].drop_duplicates(['l', 'r'])
    negatives = neg_pool.sample(n=min(len(neg_pool), args.negatives), random_state=args.seed)

    band = pd.read_csv(OUT / 'db_eval_pairs_500_enriched.csv')
    l_suf = '_l'; r_suf = '_r'
    l_base = [c[:-len(l_suf)] for c in band.columns if c.endswith(l_suf) and c not in ('eval_id', 'review_label')]
    r_base = [c[:-len(r_suf)] for c in band.columns if c.endswith(r_suf) and c not in ('eval_id', 'review_label')]
    rev_stored = pd.Series(band.match_probability.to_numpy())
    rev_records = []
    for _, r in band.iterrows():
        left = {c[:-len(l_suf)]: r[c] for c in band.columns if c.endswith(l_suf) and c not in ('eval_id', 'review_label')}
        right = {c[:-len(r_suf)]: r[c] for c in band.columns if c.endswith(r_suf) and c not in ('eval_id', 'review_label')}
        rev_records.append((left, right))

    records = index.to_dict('index')
    neg_records = [(records[str(l)], records[str(r)]) for l, r in zip(negatives.l, negatives.r)]
    neg_stored = pd.Series([
        float(preds.set_index(['l', 'r']).match_probability.get((str(l), str(r))))
        for l, r in zip(negatives.l, negatives.r)
    ])

    model, version = load_model()

    def assess(pairs, stored):
        base = score_set(pairs, model)
        base = base.sort_index()
        rows = {'pairs': len(pairs), 'gap_to_stored_max': round(float((base - stored).abs().max()), 9)}
        # AC-N1
        ac_n1 = {}
        for label, fields in VARIANTS.items():
            prob = score_set(pairs, model, fields).sort_index()
            ac_n1[label] = {
                'fields_nulled': fields,
                'pairs_rising_to_0.35_or_more': int((prob >= REVIEW).sum()),
                'max_prob_after': round(float(prob.max()), 6),
                'max_delta': round(float((prob - base).max()), 6),
            }
        # AC-N2 (hanya relevan untuk band REVIEW)
        addr = score_set(pairs, model, ['address_std']).sort_index()
        ac_n2 = {
            'pairs_rising_to_0.84_or_more': int((addr >= MATCH).sum()),
            'max_prob_after': round(float(addr.max()), 6),
            'max_delta': round(float((addr - base).max()), 6),
        }
        # AC-N3 (tidak boleh ada kenaikan saat bukti dihapus)
        ac_n3 = {
            'pairs_rising_above_base': int((addr > base + TOL).sum()),
            'max_delta': round(float((addr - base).max()), 6),
        }
        return rows, base, ac_n1, ac_n2, ac_n3

    neg_rows, neg_base, ac_n1, _, ac_n3 = assess(neg_records, neg_stored)
    rev_rows, rev_base, _, ac_n2, _ = assess(rev_records, rev_stored)

    report = {
        'model_version': version,
        'AC-N1': {'threshold': REVIEW, 'group': 'NON_MATCH', **neg_rows, **ac_n1},
        'AC-N2': {'threshold': MATCH, 'group': 'REVIEW_band', **rev_rows, **ac_n2},
        'AC-N3': {'group': 'NON_MATCH', **neg_rows, **ac_n3},
        'verdicts': {
            'AC-N1': verdict(all(v['pairs_rising_to_0.35_or_more'] == 0
                                 for v in ac_n1.values()), neg_records),
            'AC-N2': verdict(ac_n2['pairs_rising_to_0.84_or_more'] == 0, rev_records),
            'AC-N3': verdict(ac_n3['pairs_rising_above_base'] == 0, neg_records),
        },
        'negative_pool_size': int(len(neg_pool)),
        'review_band_size': len(rev_records),
        'read_only': True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'model_diagnostics_negatives.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
