"""Karena AC-4 FAIL: ukur penyebab + Langkah 4b (AC-6).

1. Ceiling blocking pada universum 40k: berapa truth pair yang bahkan tidak
   pernah menjadi kandidat (bukan salah threshold).
2. AC-6: recall near-miss (alamat + DOB berubah). Berapa yang tertangkap
   di MATCH/REVIEW, dan threshold berapa yang dibutuhkan untuk 90%.

Read-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import pandas as pd

from src.config import PROCESSED_DATA_PATH, active_path, predictions_path
from src.eval_truth import device_truth_pairs
from model_diagnostics import build_frame, load_model
from model_diagnostics_mutation import MUTATIONS, predict

OUT = Path('outputs/experiments')
MATCH = 0.84
REVIEW = 0.35


def ceiling_report() -> dict:
    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    df = df.assign(record_id=df.record_id.astype(str))
    ids = set(df.record_id)
    truth = device_truth_pairs(df)
    tp = set(zip(truth.record_id_l.astype(str), truth.record_id_r.astype(str)))

    preds = pd.read_parquet(active_path(predictions_path(full=True)))
    preds = preds.assign(
        l=preds.record_id_l.astype(str), r=preds.record_id_r.astype(str)
    )

    def count(thr):
        edges = preds[preds.match_probability >= thr]
        pairs = {(min(l, r), max(l, r)) for l, r in zip(edges.l, edges.r)}
        return len({(min(a, b), max(a, b)) for a, b in tp} & pairs)

    any_edge = {(min(l, r), max(l, r)) for l, r in zip(preds.l, preds.r)}
    tp_norm = {(min(a, b), max(a, b)) for a, b in tp}
    return {
        'universe_records': len(ids),
        'truth_pairs': len(tp_norm),
        'truth_pairs_ever_candidate': len(tp_norm & any_edge),
        'blocking_recall_ceiling': round(len(tp_norm & any_edge) / len(tp_norm), 6) if tp_norm else None,
        'truth_pairs_captured_at_0.84': count(MATCH),
        'truth_pairs_captured_at_0.35': count(REVIEW),
    }


def near_miss() -> dict:
    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    model, version = load_model()
    truth = device_truth_pairs(df).head(200)
    records = df.set_index(df.record_id.astype(str)).to_dict('index')
    pairs = [(records[str(l)], records[str(r)])
             for l, r in zip(truth.record_id_l, truth.record_id_r)]

    changes = MUTATIONS['address_and_dob']
    mutated = []
    for left, right in pairs:
        l2 = dict(left)
        for col, fn in changes.items():
            l2[col] = fn(l2.get(col))
        mutated.append((l2, right))

    pred = predict(build_frame(mutated), model)
    prob = pred.match_probability.sort_values(ascending=False).reset_index(drop=True)
    n = len(prob)
    captured = int((prob >= REVIEW).sum())
    need = int((0.9 * n) + 0.999)
    threshold_for_90 = float(prob.iloc[need - 1]) if n >= need else None

    return {
        'model_version': version,
        'pairs': n,
        'captured_at_review_0.35': captured,
        'capture_rate_at_0.35': round(captured / n, 4),
        'distribution': prob.round(6).value_counts().head(10).to_dict(),
        'threshold_needed_for_90pct_capture': threshold_for_90,
        'option_a_viable': bool(threshold_for_90 is not None and threshold_for_90 > 0.0),
        'AC-6_verdict': 'PASS' if captured / n >= 0.9 else 'FAIL',
    }


def main() -> None:
    report = {
        'blocking_ceiling': ceiling_report(),
        'near_miss': near_miss(),
        'read_only': True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'ac4_rootcause_and_ac6.json'
    path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
