"""Langkah 4: B-cubed entity-level (cluster, bukan pasangan).

Read-only. Membandingkan cluster prediksi vs truth `device_ids_std` pada
universum record yang sama, di dua threshold (0.84 dan 0.35).

AC-4: B3-F1 >= 0.99 dan largest_entity <= 3.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.config import ENTITY_MAP_PATH, PROCESSED_DATA_PATH, active_path, predictions_path

OUT = Path('outputs/experiments')
MATCH = 0.84
REVIEW = 0.35


class UF:
    def __init__(self, ids):
        self.p = {i: i for i in ids}

    def find(self, x):
        p = self.p
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra

    def clusters(self):
        g = defaultdict(set)
        for i in self.p:
            g[self.find(i)].add(i)
        return g


def b_cubed(pred: dict[str, str], truth: dict[str, str]) -> dict:
    ids = list(truth)
    pred_g = defaultdict(set)
    truth_g = defaultdict(set)
    for i in ids:
        pred_g[pred.get(i, i)].add(i)
        truth_g[truth[i]].add(i)

    ps, rs = [], []
    for i in ids:
        pc = pred_g[pred.get(i, i)]
        tc = truth_g[truth[i]]
        overlap = len(pc & tc)
        ps.append(overlap / len(pc))
        rs.append(overlap / len(tc))
    p = sum(ps) / len(ps)
    r = sum(rs) / len(rs)
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    sizes = pd.Series([len(v) for v in pred_g.values()])
    return {
        'records': len(ids),
        'clusters': int(sizes.size),
        'b3_precision': round(p, 6),
        'b3_recall': round(r, 6),
        'b3_f1': round(f1, 6),
        'largest_entity': int(sizes.max()) if sizes.size else 0,
        'entities_size_ge2': int((sizes >= 2).sum()),
    }


def main() -> None:
    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    df = df.assign(record_id=df.record_id.astype(str))
    truth_col = 'device_ids_std' if 'device_ids_std' in df.columns else None
    if truth_col is None:
        raise SystemExit('no device_ids_std column in processed data')
    df = df[df[truth_col].notna()].copy()
    truth = dict(zip(df.record_id, df[truth_col].astype(str)))
    universe = list(truth)

    preds = pd.read_parquet(active_path(predictions_path(full=True)))
    preds = preds.assign(
        l=preds.record_id_l.astype(str), r=preds.record_id_r.astype(str)
    )

    reports = {'truth_source': 'device_ids_std', 'universe': len(universe), 'thresholds': {}}

    for name, thr in (('0.84', MATCH), ('0.35', REVIEW)):
        edges = preds[preds.match_probability >= thr]
        uf = UF(universe)
        for l, r in zip(edges.l, edges.r):
            if l in uf.p and r in uf.p:
                uf.union(l, r)
        pred_map = {i: uf.find(i) for i in universe}
        res = b_cubed(pred_map, truth)
        # entity yang mencampur >=2 device id
        mix = 0
        for root, members in uf.clusters().items():
            if len({truth[m] for m in members}) > 1:
                mix += 1
        res['entities_mixing_two_device_ids'] = mix
        reports['thresholds'][name] = res

    # Artefak produksi (entity_map) pada universum yang sama
    if ENTITY_MAP_PATH.exists():
        em = pd.read_parquet(ENTITY_MAP_PATH)
        em = em.assign(record_id=em.record_id.astype(str))
        prod = dict(zip(em.record_id, em.entity_id.astype(str)))
        prod_map = {i: f"prod_{prod[i]}" if i in prod else i for i in universe}
        res = b_cubed(prod_map, truth)
        reports['entity_map_artifact'] = res

    thr = reports['thresholds']
    ok = all(v['b3_f1'] >= 0.99 and v['largest_entity'] <= 3 for v in thr.values())
    reports['AC-4'] = {
        'rule': 'B3-F1 >= 0.99 dan largest_entity <= 3 pada 0.84 dan 0.35',
        'verdict': 'PASS' if ok else 'FAIL',
    }
    reports['read_only'] = True

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'b_cubed_entity_level.json'
    path.write_text(json.dumps(reports, indent=2), encoding='utf-8')
    print(json.dumps(reports, indent=2))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
