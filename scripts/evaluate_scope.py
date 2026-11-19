"""Evaluasi per lapisan untuk potongan record tertentu (scope konsisten).

Berbeda dari `src.evaluate --full` yang mencampur parquet 40k dengan prediksi
DB 110k, skrip ini menjalankan inferensi ulang dengan model tersimpan pada
potongan yang dievaluasi, sehingga record, prediksi, dan entity berada pada
cakupan yang sama.

Read-only: tidak menulis DB, tidak melatih ulang, tidak mengubah artefak.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.config import MATCH_THRESHOLD, PROCESSED_DATA_PATH, PROJECT_ROOT, REVIEW_THRESHOLD, active_path
from src.splink_model import train_and_predict
from src.eval_truth import device_truth_pairs

OUT = Path('outputs/experiments')


def load_model() -> dict:
    latest = json.loads((PROJECT_ROOT / 'models' / 'latest.json').read_text(encoding='utf-8'))
    path = Path(latest['path']) / 'model.json'
    return json.loads(path.read_text(encoding='utf-8')), latest['version']


def clusters(record_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, str]:
    parent = {r: r for r in record_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    return {r: find(r) for r in record_ids}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=10000)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--head', action='store_true', help='ambil N pertama, bukan acak')
    args = parser.parse_args()

    started = time.perf_counter()
    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    total_available = len(df)
    if args.head:
        sub = df.iloc[args.offset:args.offset + args.rows].copy()
    else:
        sub = df.sample(n=min(len(df), args.rows), random_state=42).copy()

    model, version = load_model()
    preds, _ = train_and_predict(sub, model=model, verbose=False)
    preds = preds[preds.record_id_l.astype(str).ne(preds.record_id_r.astype(str))].copy()

    ids = set(sub.record_id.astype(str))
    truth = device_truth_pairs(sub)
    truth = truth[
        truth.record_id_l.astype(str).isin(ids) & truth.record_id_r.astype(str).isin(ids)
    ].copy()

    cand = set(zip(preds.record_id_l.astype(str), preds.record_id_r.astype(str)))
    truth_pairs = set(zip(truth.record_id_l.astype(str), truth.record_id_r.astype(str)))
    covered = len(truth_pairs & cand)

    edges = preds[preds.match_probability >= MATCH_THRESHOLD]
    edge_pairs = set(zip(edges.record_id_l.astype(str), edges.record_id_r.astype(str)))
    tp = len(edge_pairs & truth_pairs)
    fp = len(edge_pairs - truth_pairs)
    fn = len(truth_pairs - edge_pairs)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None

    counts = preds.decision.value_counts().to_dict()

    # Entity layer: union-find on MATCH edges, dibandingkan dengan device truth.
    cmap = clusters(list(ids), list(edge_pairs))
    sizes = pd.Series(list(cmap.values())).value_counts()
    truth_by_pair = truth.assign(
        l=truth.record_id_l.astype(str), r=truth.record_id_r.astype(str)
    )
    same = sum(
        1 for l, r in zip(truth_by_pair.l, truth_by_pair.r) if cmap.get(l) == cmap.get(r)
    )
    device_of = dict(
        zip(sub.record_id.astype(str), sub.get('device_ids_std', pd.Series(index=sub.index)).astype(str))
    ) if 'device_ids_std' in sub.columns else {}
    mixing = 0
    if device_of:
        for root, group in pd.Series(cmap).groupby(pd.Series(cmap)):
            devs = {device_of.get(r) for r in group.index}
            if len(devs) > 1:
                mixing += 1

    report = {
        'scope': 'random' if not args.head else f'head_offset{args.offset}',
        'rows_requested': args.rows,
        'rows_evaluated': len(sub),
        'rows_available_in_parquet': total_available,
        'model_version': version,
        'runtime_seconds': round(time.perf_counter() - started, 2),
        'blocking': {
            'candidate_pairs': len(preds),
            'truth_pairs': len(truth_pairs),
            'truth_pairs_in_candidates': covered,
            'blocking_recall_ceiling': round(covered / len(truth_pairs), 6) if truth_pairs else None,
        },
        'linkage': {
            'threshold': MATCH_THRESHOLD,
            'match_edges': len(edge_pairs),
            'tp': tp, 'fp': fp, 'fn': fn,
            'precision': round(precision, 4) if precision is not None else None,
            'recall': round(recall, 4) if recall is not None else None,
        },
        'decision': {
            'counts': counts,
            'review_volume': counts.get('REVIEW', 0),
            'thresholds': {'match': MATCH_THRESHOLD, 'review': REVIEW_THRESHOLD},
        },
        'entity': {
            'entities': int(sizes.size),
            'largest_entity': int(sizes.max()) if sizes.size else 0,
            'entities_size_ge2': int((sizes >= 2).sum()),
            'truth_pairs_in_one_entity': same,
            'truth_pairs_total': len(truth_pairs),
            'entities_mixing_two_device_ids': mixing,
        },
        'read_only': True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f'evaluate_rows_{args.rows}.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
