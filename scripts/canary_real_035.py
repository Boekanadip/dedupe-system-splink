"""Langkah 8: canary NYATA threshold 0.35, desain paired same-input.

    --input db    : gunakan splink_data.processed_customers (DOB DB rusak,
                     60% NULL + swap hari/bulan). 57.500 record.
    --input clean : gunakan data/processed/crm_standardized.parquet
                     (DOB dayfirst benar, 40.000 record).

    Arsitektur: satu pass scoring prediksi, dua arm dibandingkan
    (threshold 0.84 vs 0.35), gate PASS jika kondisi berikut dipenuhi.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import pandas as pd
import psycopg2
import psycopg2.extras as ext

from src.standardize import add_blocking_keys, soundex
from src.splink_model import train_and_predict
from b_cubed import UF

SCHEMA = 'splink_canary_035'
CANARY_THRESHOLD = 0.35
BASE_THRESHOLD = 0.84
OUT = Path('outputs/experiments')


def connect():
    return psycopg2.connect(host='localhost', port=5432, dbname='crm',
                            user='crm_user', password='crm_password_2026',
                            connect_timeout=5)


def load_input(conn, source: str) -> pd.DataFrame:
    """Memuat input sesuai sumber.

    source=db  : splink_data.processed_customers (dob rusak: 60% NULL,
    hari/bulan tertukar). 57.500 record.
    source=clean: data/processed/crm_standardized.parquet (dob benar, 40k).
    """
    if source == 'db':
        df = pd.read_sql('SELECT * FROM splink_data.processed_customers', conn)
        if 'dob_std' in df.columns:
            df['dob_std'] = pd.to_datetime(df.dob_std, errors='coerce').dt.strftime('%Y-%m-%d')
    elif source == 'clean':
        df = pd.read_parquet('data/processed/crm_standardized.parquet')
    else:
        raise SystemExit(f'input tidak dikenal: {source}')
    df['record_id'] = df.record_id.astype(str)
    df['phonetic_first_name'] = df.first_name_std.map(soundex)
    df['phonetic_last_name'] = df.last_name_std.map(soundex)
    return add_blocking_keys(df)


def cluster(universe: list[str], edges: pd.DataFrame) -> pd.DataFrame:
    uf = UF(universe)
    for l, r in zip(edges.record_id_l, edges.record_id_r):
        if l in uf.p and r in uf.p:
            uf.union(l, r)
    return pd.DataFrame({'record_id': universe, 'entity_id': [uf.find(i) for i in universe]})


def arm_stats(mapping: pd.DataFrame) -> dict:
    sizes = mapping.entity_id.value_counts()
    return {
        'entities': int(sizes.size),
        'largest_entity': int(sizes.max()),
        'entities_size_ge2': int((sizes >= 2).sum()),
        'records_in_multi': int(sizes[sizes >= 2].sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', choices=['db', 'clean'], default='db',
                        help='source of processed_customers data')
    args = parser.parse_args()

    started = time.perf_counter()
    source = args.input
    schema = SCHEMA if source == 'db' else f'{SCHEMA}_clean'
    conn = connect()
    cur = conn.cursor()

    cur.execute(f'CREATE SCHEMA IF NOT EXISTS {schema}')
    for t in ('predictions', 'entity_map', 'summary'):
        cur.execute(f'DROP TABLE IF EXISTS {schema}.{t}')
    conn.commit()

    df = load_input(conn, source)
    print(f'records: {len(df)} | input: {source}')

    model, version = train_and_predict.__globals__['load_model']() if False \
        else (json.loads((Path('models') / 'latest.json').read_text(encoding='utf-8')),
              None)  # versi tidak kunci; Pair arm derivation uses same model
    # Proper load:
    latest = json.loads((Path('models') / 'latest.json').read_text(encoding='utf-8'))
    model = json.loads((Path(latest['path']) / 'model.json').read_text(encoding='utf-8'))
    version = latest['version']
    print(f'model: {version}')

    preds, _ = train_and_predict(df, model=model, verbose=False)
    preds = preds.assign(
        record_id_l=preds.record_id_l.astype(str),
        record_id_r=preds.record_id_r.astype(str),
    )
    preds = preds[preds.record_id_l.ne(preds.record_id_r)]
    preds['match_probability'] = preds.match_probability.astype(float)
    print(f'pairs: {len(preds)} | decisions: {preds.decision.value_counts().to_dict()}')

    universe = df.record_id.tolist()
    arm_base = cluster(universe, preds[preds.match_probability >= BASE_THRESHOLD])
    arm_canary = cluster(universe, preds[preds.match_probability >= CANARY_THRESHOLD])
    base_stats, canary_stats = arm_stats(arm_base), arm_stats(arm_canary)

    review = preds[(preds.match_probability >= CANARY_THRESHOLD)
                   & (preds.match_probability < BASE_THRESHOLD)].copy()

    # Label band REVIEW menggunakan label yg sudah ada.
    labels = pd.read_csv(OUT / 'db_eval_pairs_500_enriched.csv')
    labels = labels.assign(
        record_id_l=labels.record_id_l.astype(str),
        record_id_r=labels.record_id_r.astype(str),
        gold=labels.gold_label.astype(str).str.lower(),
    )
    lab = review.merge(labels[['record_id_l', 'record_id_r', 'gold']],
                       on=['record_id_l', 'record_id_r'], how='left')
    labelled = lab[lab.gold.notna()]
    false_merges = int(labelled.gold.eq('non_match').sum())

    eid = arm_canary.set_index('record_id').entity_id
    review_pairs_merged = int(sum(
        eid.get(l) == eid.get(r) for l, r in zip(review.record_id_l, review.record_id_r)
    ))

    # Tulis artefak ke schema staging terpisah
    cur.execute(f"""
        CREATE TABLE {schema}.predictions (
            record_id_l TEXT, record_id_r TEXT,
            match_probability DOUBLE PRECISION, match_weight DOUBLE PRECISION,
            decision TEXT, business_rule TEXT, canary_decision TEXT
        )
    """)
    out_preds = preds[['record_id_l', 'record_id_r', 'match_probability',
                       'match_weight', 'decision', 'business_rule']].copy()
    out_preds['canary_decision'] = out_preds.match_probability >= CANARY_THRESHOLD
    ext.execute_values(cur, f'INSERT INTO {schema}.predictions VALUES %s',
                       list(out_preds.itertuples(index=False, name=None)), page_size=2000)

    cur.execute(f"""
        CREATE TABLE {schema}.entity_map (
            record_id TEXT PRIMARY KEY, entity_id TEXT, cluster_size INTEGER
        )
    """)
    sizes = arm_canary.entity_id.value_counts()
    arm_canary['cluster_size'] = arm_canary.entity_id.map(sizes)
    ext.execute_values(cur, f'INSERT INTO {schema}.entity_map VALUES %s',
                       list(arm_canary.itertuples(index=False, name=None)), page_size=2000)

    summary = {
        'run_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'model_version': version,
        'records': int(len(universe)),
        'pairs': int(len(preds)),
        'canary_threshold': CANARY_THRESHOLD,
        'baseline_threshold': BASE_THRESHOLD,
        'staging_schema': schema,
        'production_written': False,
        'input_source': source,
    }
    cur.execute(f"""
        CREATE TABLE {schema}.summary (
            run_at TEXT, model_version TEXT, records INTEGER, pairs INTEGER,
            canary_threshold DOUBLE PRECISION, baseline_threshold DOUBLE PRECISION,
            staging_schema TEXT, production_written BOOLEAN, input_source TEXT
        )
    """)
    cur.execute(f'INSERT INTO {schema}.summary VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (summary['run_at'], summary['model_version'], summary['records'],
                 summary['pairs'], summary['canary_threshold'],
                 summary['baseline_threshold'], summary['staging_schema'],
                 summary['production_written'], summary['input_source']))
    conn.commit()

    gate = {
        'production_untouched': True,
        'review_pairs_merged': review_pairs_merged == len(review),
        'false_merge_on_review_band': false_merges == 0,
        'largest_entity_not_increased': canary_stats['largest_entity'] <= base_stats['largest_entity'],
        'entity_delta_equals_review_pairs': canary_stats['entities'] - base_stats['entities'] == -len(review),
        'review_band_all_labelled_match': len(labelled) == len(review) and false_merges == 0,
    }

    report_name = 'canary_035_real.json' if source == 'db' else 'canary_035_real_clean.json'
    report = {
        'mode': 'paired_same_input_staging_schema',
        'staging_schema': schema,
        'production_schema': 'splink_data (read only, not baseline)',
        'model_version': version,
        'runtime_seconds': round(time.perf_counter() - started, 2),
        'arm_baseline_084': base_stats,
        'arm_canary_035': canary_stats,
        'delta': {
            'entities': canary_stats['entities'] - base_stats['entities'],
            'records_in_multi': canary_stats['records_in_multi'] - base_stats['records_in_multi'],
            'largest_entity': canary_stats['largest_entity'] - base_stats['largest_entity'],
        },
        'review_band': {
            'pairs': int(len(review)),
            'pairs_merged_into_one_entity': review_pairs_merged,
            'pairs_with_existing_label': int(len(labelled)),
            'labeled_match': int(labelled.gold.eq('match').sum()),
            'labeled_non_match': false_merges,
        },
        'gate': gate,
        'verdict': 'PASS' if all(gate.values()) else 'FAIL',
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / report_name
    path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))
    print(f'\nSaved: {path}')
    conn.close()


if __name__ == '__main__':
    main()