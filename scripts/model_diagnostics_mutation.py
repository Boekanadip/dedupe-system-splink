"""Prioritas 3: robustness mutasi field (satu field, satu sisi).

Read-only. Model tersimpan dipakai ulang; blocking diganti rule konstan
`l._pairkey = r._pairkey`. Sampel = 200 pasangan device-truth (semua true match).

AC-3: mutasi 1 digit telepon / 1 huruf nama tidak menurunkan P di bawah 0.84
      pada >= 95% pasangan.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import pandas as pd

from src.config import PROCESSED_DATA_PATH, active_path
from src.eval_truth import device_truth_pairs
from model_diagnostics import build_frame, forced_settings, load_model

from splink import DuckDBAPI, Linker

OUT = Path('outputs/experiments')
MATCH = 0.84
REVIEW = 0.35


def predict(frame: pd.DataFrame, model: dict) -> pd.DataFrame:
    sdf = DuckDBAPI().register(frame, table_name='pairs')
    linker = Linker(sdf, forced_settings(model))
    preds = linker.inference.predict().as_pandas_dataframe()
    preds['_pairkey'] = preds['record_id_l'].astype(str).str.split('_').str[0].astype(int)
    return preds.set_index('_pairkey')[['match_probability', 'match_weight']].sort_index()


def _s(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return str(value)


def typo_name(v):
    t = _s(v)
    if not t:
        return v
    if len(t) < 2:
        return t + 'x'
    return t[0] + t[2] + t[1] + t[3:]


def shift_phone(v):
    t = _s(v)
    if not t:
        return v
    last = t[-1]
    if not last.isdigit():
        return t + '1'
    return t[:-1] + str((int(last) + 1) % 10)


def switch_domain(v):
    t = _s(v)
    if not t or '@' not in t:
        return v
    local, _, _domain = t.partition('@')
    return f'{local}@mail-typo.co'


def bump_address_number(v):
    t = _s(v)
    if not t:
        return v
    m = re.search(r'\d+', t)
    if not m:
        return t + ' 1'
    n = int(m.group(0))
    return t[: m.start()] + str(n + 1) + t[m.end():]


def shift_dob_year(v):
    t = _s(v)
    if not t:
        return v
    m = re.match(r'^(\d{4})(.*)$', t)
    if not m:
        return v
    return str(int(m.group(1)) + 1) + m.group(2)


MUTATIONS = {
    'name_typo_1char': {'first_name_std': typo_name},
    'name_phonetic_diff': {'first_name_std': typo_name, 'phonetic_first_name': typo_name},
    'phone_1digit': {'phone_std': shift_phone},
    'email_domain': {'email_std': switch_domain},
    'address_number': {'address_std': bump_address_number},
    'dob_year_plus1': {'dob_std': shift_dob_year},
    'address_and_dob': {'address_std': bump_address_number, 'dob_std': shift_dob_year},
}

TYPO_GATE = {'name_typo_1char', 'phone_1digit'}


def main() -> None:
    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    model, version = load_model()
    truth = device_truth_pairs(df).head(200)

    records = df.set_index(df.record_id.astype(str)).to_dict('index')
    pairs = [(records[str(l)], records[str(r)])
             for l, r in zip(truth.record_id_l, truth.record_id_r)]

    base = predict(build_frame(pairs), model)
    results = {}
    for name, changes in MUTATIONS.items():
        mutated = []
        for left, right in pairs:
            l2 = dict(left)
            for col, fn in changes.items():
                l2[col] = fn(l2.get(col))
            mutated.append((l2, right))
        pred = predict(build_frame(mutated), model)
        delta = pred.match_probability - base.match_probability
        dw = pred.match_weight - base.match_weight
        results[name] = {
            'fields_mutated': list(changes),
            'pairs_with_weight_change': int((dw.abs() > 1e-9).sum()),
            'mean_weight_delta': round(float(dw.mean()), 4),
            'min_weight_delta': round(float(dw.min()), 4),
            'mean_prob_delta': round(float(delta.mean()), 8),
            'max_prob_drop': round(float(delta.min()), 8),
            'min_prob_after': round(float(pred.match_probability.min()), 6),
            'pairs_below_0.84': int((pred.match_probability < MATCH).sum()),
            'pairs_below_0.35': int((pred.match_probability < REVIEW).sum()),
            'pass_rate_at_0.84': round(float((pred.match_probability >= MATCH).mean()), 4),
            'ac3_gate': name in TYPO_GATE,
        }

    gate = [v for k, v in results.items() if v['ac3_gate']]
    verdict = 'PASS' if all(v['pass_rate_at_0.84'] >= 0.95 for v in gate) else 'FAIL'

    report = {
        'model_version': version,
        'pairs_tested': len(pairs),
        'base_all_above_0.84': bool((base.match_probability >= MATCH).all()),
        'base_min_probability': round(float(base.match_probability.min()), 6),
        'base_mean_match_weight': round(float(base.match_weight.mean()), 4),
        'mutations': results,
        'AC-3': {
            'rule': 'mutasi 1 digit telepon / 1 huruf nama: P >= 0.84 pada >= 95% pasangan',
            'gated_mutations': sorted(TYPO_GATE),
            'verdict': verdict,
        },
        'read_only': True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'model_diagnostics_mutation.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
