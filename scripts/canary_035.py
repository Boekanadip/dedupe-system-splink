"""Langkah 6: dry-run canary threshold 0.35 pada scope DB (read-only).

Baseline = outputs/entity_map.parquet (dibangun pada threshold 0.84).
Kandidat  = baseline + seluruh edge P >= 0.35 (MATCH + REVIEW).

Tidak menulis DB, tidak mengubah config, tidak menyentuh pipeline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import pandas as pd

from src.config import ENTITY_MAP_PATH, PROCESSED_DATA_PATH, active_path, predictions_path
from b_cubed import UF

OUT = Path('outputs/experiments')
MATCH = 0.84
REVIEW = 0.35


def db_available() -> tuple[bool, str]:
    try:
        import psycopg2

        c = psycopg2.connect(host='localhost', port=5432, dbname='crm',
                             user='crm_user', password='crm_password_2026', connect_timeout=3)
        c.close()
        return True, 'ok'
    except Exception as exc:
        return False, f'{type(exc).__name__}: {str(exc).splitlines()[0]}'


def main() -> None:
    em = pd.read_parquet(active_path(ENTITY_MAP_PATH))
    em = em.assign(record_id=em.record_id.astype(str), entity_id=em.entity_id.astype(str))
    baseline = dict(zip(em.record_id, em.entity_id))
    universe = list(baseline)

    base_sizes = pd.Series(list(baseline.values())).value_counts()

    preds = pd.read_parquet(active_path(predictions_path(full=True)))
    preds = preds.assign(
        l=preds.record_id_l.astype(str), r=preds.record_id_r.astype(str)
    )
    added = preds[preds.decision.eq('REVIEW')]

    uf = UF(universe)
    canary_edges = preds[preds.decision.ne('NON_MATCH')]
    for l, r in zip(canary_edges.l, canary_edges.r):
        if l in uf.p and r in uf.p:
            uf.union(l, r)
    canary = {i: uf.find(i) for i in universe}
    canary_sizes = pd.Series(list(canary.values())).value_counts()

    # Edge REVIEW: berapa yang benar-benar menggabungkan dua entity berbeda
    real_merges = 0
    for l, r in zip(added.l, added.r):
        if baseline.get(l) != baseline.get(r) and canary[l] == canary[r]:
            real_merges += 1

    labels = pd.read_csv(OUT / 'db_eval_pairs_500_enriched.csv')
    band = labels[(labels.match_probability >= REVIEW) & (labels.match_probability < MATCH)]
    false_merge_labels = int((band.gold_label.astype(str).str.lower() == 'non_match').sum())

    # Device mixing pada irisan yang punya device truth
    dev = pd.read_parquet(active_path(PROCESSED_DATA_PATH), columns=['record_id', 'device_ids_std'])
    dev = dev.assign(record_id=dev.record_id.astype(str))
    dev = dev[dev.device_ids_std.notna()]
    device_of = dict(zip(dev.record_id, dev.device_ids_std.astype(str)))
    overlap = [i for i in universe if i in device_of]

    def mixing(mapping):
        groups: dict[str, set] = {}
        for i in overlap:
            groups.setdefault(mapping[i], set()).add(device_of[i])
        return sum(1 for v in groups.values() if len(v) > 1)

    ok, db_msg = db_available()

    gate = {
        'false_merge_on_review_band': false_merge_labels == 0,
        'largest_entity_not_increased': bool(canary_sizes.max() <= base_sizes.max()),
        'device_mixing_not_increased': mixing(canary) <= mixing(baseline),
        'review_volume_within_capacity': len(added) <= 200,
    }

    report = {
        'mode': 'dry_run_local (staging DB tidak tersedia)',
        'staging_db': {'available': ok, 'message': db_msg},
        'scope': {'records': len(universe), 'source': 'outputs/entity_map.parquet'},
        'thresholds': {'review': REVIEW, 'match': MATCH},
        'baseline_0.84': {
            'entities': int(base_sizes.size),
            'largest_entity': int(base_sizes.max()),
            'entities_size_ge2': int((base_sizes >= 2).sum()),
            'entities_mixing_devices': mixing(baseline),
        },
        'canary_0.35': {
            'entities': int(canary_sizes.size),
            'largest_entity': int(canary_sizes.max()),
            'entities_size_ge2': int((canary_sizes >= 2).sum()),
            'entities_mixing_devices': mixing(canary),
            'entity_count_delta_vs_baseline': int(canary_sizes.size - base_sizes.size),
            'baseline_entities_absorbed': real_merges,
        },
        'review_band': {
            'pairs_added': int(len(added)),
            'pairs_that_merge_two_entities': real_merges,
            'labeled_non_match_among_added': false_merge_labels,
            'labeled_match_among_added': int((band.gold_label.astype(str).str.lower() == 'match').sum()),
        },
        'device_truth_overlap_records': len(overlap),
        'gate': gate,
        'verdict': 'PASS' if all(gate.values()) else 'FAIL',
        'read_only': True,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'canary_035_dry_run.json'
    path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
