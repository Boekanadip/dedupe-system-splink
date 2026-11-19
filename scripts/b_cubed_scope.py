"""Langkah 5a: AC-4b — B-cubed pada universum yang sama.

Prediksi dihasilkan ulang dengan model tersimpan + blocking rule model pada
40k record parquet, sehingga record, kandidat, dan entity satu cakupan.
Read-only: tidak melatih ulang, tidak menulis DB, tidak mengubah artefak.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import pandas as pd

from src.config import PROCESSED_DATA_PATH, active_path
from src.eval_truth import device_truth_pairs
from src.splink_model import train_and_predict
from b_cubed import UF, b_cubed
from model_diagnostics import load_model

OUT = Path('outputs/experiments')
MATCH = 0.84
REVIEW = 0.35


def main() -> None:
    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    df = df.assign(record_id=df.record_id.astype(str))
    df = df[df.device_ids_std.notna()].copy()
    truth = dict(zip(df.record_id, df.device_ids_std.astype(str)))
    universe = list(truth)

    model, version = load_model()
    preds, _ = train_and_predict(df, model=model, verbose=False)
    preds = preds.assign(
        l=preds.record_id_l.astype(str), r=preds.record_id_r.astype(str)
    )
    preds = preds[preds.l.ne(preds.r)]

    tp = {(min(a, b), max(a, b)) for a, b in
          zip(*[device_truth_pairs(df)[c].astype(str) for c in ('record_id_l', 'record_id_r')])}
    cand = {(min(l, r), max(l, r)) for l, r in zip(preds.l, preds.r)}

    report = {
        'model_version': version,
        'scope': '40k processed parquet, same universe for truth/candidates/entities',
        'universe_records': len(universe),
        'truth_pairs': len(tp),
        'candidate_pairs': len(cand),
        'truth_pairs_in_candidates': len(tp & cand),
        'blocking_recall_ceiling': round(len(tp & cand) / len(tp), 6) if tp else None,
        'thresholds': {},
        'read_only': True,
    }

    for name, thr in (('0.84', MATCH), ('0.35', REVIEW)):
        edges = preds[preds.match_probability >= thr]
        uf = UF(universe)
        for l, r in zip(edges.l, edges.r):
            if l in uf.p and r in uf.p:
                uf.union(l, r)
        pred_map = {i: uf.find(i) for i in universe}
        res = b_cubed(pred_map, truth)
        res['entities_mixing_two_device_ids'] = sum(
            1 for members in uf.clusters().values()
            if len({truth[m] for m in members}) > 1
        )
        res['decision_counts'] = preds.decision.value_counts().to_dict() if thr == MATCH else None
        report['thresholds'][name] = res

    thr = report['thresholds']
    ok = all(v['b3_f1'] >= 0.99 and v['largest_entity'] <= 3 for v in thr.values())
    report['AC-4b'] = {
        'rule': 'B3-F1 >= 0.99 dan largest_entity <= 3 pada 0.84 dan 0.35 (scope konsisten)',
        'verdict': 'PASS' if ok else 'FAIL',
    }

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'b_cubed_scope_consistent.json'
    path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
