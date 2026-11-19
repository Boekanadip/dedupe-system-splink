from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--predictions', default='outputs/splink_predictions.parquet')
    parser.add_argument('--entity-map', default='outputs/entity_map.parquet')
    parser.add_argument('--blocking-benchmark', default='outputs/blocking_benchmark.csv')
    parser.add_argument('--output', default='outputs/experiments/batch_monitor_latest.json')
    args = parser.parse_args()
    started = time.perf_counter()
    result = {'source': args.predictions, 'read_only': True, 'errors': []}
    try:
        p = pd.read_parquet(args.predictions)
        result['predictions'] = {'rows': len(p), 'decisions': p.decision.value_counts().to_dict()}
    except Exception as exc:
        result['errors'].append(f'predictions: {type(exc).__name__}: {exc}')
    try:
        em = pd.read_parquet(args.entity_map)
        sizes = em.groupby('entity_id').size()
        result['entities'] = {'records': len(em), 'entities': int(em.entity_id.nunique()), 'largest_entity': int(sizes.max()), 'entities_size_ge2': int((sizes >= 2).sum())}
    except Exception as exc:
        result['errors'].append(f'entity_map: {type(exc).__name__}: {exc}')
    try:
        b = pd.read_csv(args.blocking_benchmark)
        rule_col = 'rule' if 'rule' in b.columns else b.columns[0]
        name = b[rule_col].astype(str).str.strip('_').str.upper()
        union = b[name.eq('UNION')]
        cols = [c for c in ('rule', 'candidate_pairs', 'runtime_seconds',
                            'largest_block_rows', 'device_truth_coverage_pct',
                            'coverage_pct') if c in b.columns]
        result['blocking'] = {
            'rules_benchmarked': int(len(b) - len(union)),
            'union': union[cols].to_dict('records') if not union.empty else None,
            'top_rules_by_candidates': b[name.ne('UNION')]
                .nlargest(5, 'candidate_pairs')[cols].to_dict('records') if 'candidate_pairs' in b.columns else None,
        }
    except Exception as exc:
        result['errors'].append(f'blocking: {type(exc).__name__}: {exc}')
    result['runtime_seconds'] = round(time.perf_counter() - started, 3)
    result['status'] = 'ok' if not result['errors'] else 'error'
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    print(json.dumps(result, indent=2, default=str))

if __name__ == '__main__':
    main()
