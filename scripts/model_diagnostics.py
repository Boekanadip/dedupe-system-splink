"""Diagnostik model: simetri + null-handling.

Read-only. Model tersimpan dipakai ulang; blocking diganti rule konstan
`l._pairkey = r._pairkey` supaya pasangan yang diuji pasti dinilai.
Tidak melatih ulang, tidak menulis DB.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from splink import DuckDBAPI, Linker

from src.config import PROCESSED_DATA_PATH, PROJECT_ROOT, active_path
from src.eval_truth import device_truth_pairs

OUT = Path('outputs/experiments')
NULL_FIELDS = ['email_std', 'phone_std', 'dob_std', 'address_std']


def load_model() -> tuple[dict, str]:
    latest = json.loads((PROJECT_ROOT / 'models' / 'latest.json').read_text(encoding='utf-8'))
    model = json.loads((Path(latest['path']) / 'model.json').read_text(encoding='utf-8'))
    return model, latest['version']


def forced_settings(model: dict) -> dict:
    settings = json.loads(json.dumps(model))
    settings['blocking_rules_to_generate_predictions'] = [
        {'blocking_rule': 'l."_pairkey" = r."_pairkey"', 'sql_dialect': 'duckdb'}
    ]
    return settings


def score_pairs(frame: pd.DataFrame, model: dict) -> pd.Series:
    sdf = DuckDBAPI().register(frame, table_name='pairs')
    linker = Linker(sdf, forced_settings(model))
    preds = linker.inference.predict().as_pandas_dataframe()
    preds['_pairkey'] = preds['record_id_l'].astype(str).str.split('_').str[0].astype(int)
    return preds.set_index('_pairkey')['match_probability']


def build_frame(pairs: list[tuple[dict, dict]]) -> pd.DataFrame:
    rows = []
    for i, (left, right) in enumerate(pairs):
        rows.append({**left, 'record_id': f'{i}_l', '_pairkey': i})
        rows.append({**right, 'record_id': f'{i}_r', '_pairkey': i})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pairs', type=int, default=200)
    args = parser.parse_args()

    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    model, version = load_model()
    truth = device_truth_pairs(df).head(args.pairs)

    index = df.set_index(df.record_id.astype(str))
    records = index.to_dict('index')
    pairs = [(records[str(l)], records[str(r)]) for l, r in zip(truth.record_id_l, truth.record_id_r)]

    base = score_pairs(build_frame(pairs), model)

    # 1. Simetri: tukar sisi kiri/kanan.
    swapped = score_pairs(build_frame([(b, a) for a, b in pairs]), model)
    symmetry = (base - swapped).abs()

    # 2. Null-handling: null-kan satu field (atau kombinasi) di sisi kiri.
    null_results = {}
    variants = {f: [f] for f in NULL_FIELDS}
    variants['contacts_both'] = ['email_std', 'phone_std']
    variants['name_both'] = ['first_name_std', 'last_name_std']
    variants['address_and_dob'] = ['address_std', 'dob_std']
    for label, fields in variants.items():
        mutated = []
        for left, right in pairs:
            l2 = dict(left)
            for field in fields:
                l2[field] = None
            mutated.append((l2, right))
        prob = score_pairs(build_frame(mutated), model)
        delta = prob - base
        null_results[label] = {
            'fields_nulled': fields,
            'mean_delta': round(float(delta.mean()), 6),
            'median_delta': round(float(delta.median()), 6),
            'max_abs_delta': round(float(delta.abs().max()), 6),
            'pairs_dropped_below_0.84': int((prob < 0.84).sum()),
            'pairs_above_0.84_before': int((base >= 0.84).sum()),
            'pairs_still_above_0.84': int((prob >= 0.84).sum()),
        }

    report = {
        'model_version': version,
        'pairs_tested': len(pairs),
        'symmetry': {
            'max_abs_diff': float(symmetry.max()),
            'mean_abs_diff': round(float(symmetry.mean()), 10),
            'pairs_with_diff': int((symmetry > 1e-9).sum()),
            'verdict': 'symmetric' if float(symmetry.max()) <= 1e-9 else 'ASYMMETRIC',
        },
        'null_handling': null_results,
        'base_match_rate_at_0.84': round(float((base >= 0.84).mean()), 4),
        'read_only': True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'model_diagnostics_symmetry_null.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
