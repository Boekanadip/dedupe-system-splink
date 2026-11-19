"""Langkah 7: audit entity berukuran 10 dari entity_map (read-only).

Tarik 10 record terbesar dari outputs/entity_map.parquet,
gabungkan data master dari data/processed (jika tersedia),
tampilkan nama/email/telepon/dob/address untuk diikutsar apakah
ini 1 identitas nyata atau chain merge.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.config import ENTITY_MAP_PATH, PROCESSED_DATA_PATH, active_path

OUT = Path('outputs/experiments')


def main() -> None:
    em = pd.read_parquet(active_path(ENTITY_MAP_PATH))
    em = em.assign(record_id=em.record_id.astype(str), entity_id=em.entity_id.astype(str))
    sizes = em.groupby('entity_id').size()
    largest_eid = sizes.idxmax()
    largest_size = sizes.max()

    members = em[em.entity_id.eq(largest_eid)].record_id.tolist()
    print(f'entity_id terpanjang: {largest_eid} ({largest_size} record)')
    print('record_id:', members)
    print()

    master = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    master = master.assign(record_id=master.record_id.astype(str))
    cols = [c for c in master.columns if c not in ('record_id',)]
    master = master[master.record_id.isin(members)]
    show_cols = ['record_id', 'customer_id', 'first_name_std', 'last_name_std',
                 'email_std', 'phone_std', 'dob_std', 'address_std', 'city_std']
    show_cols = [c for c in show_cols if c in master.columns]
    master = master[show_cols].sort_values('record_id')
    out = master.to_dict('records')

    report = {
        'entity_id': largest_eid,
        'entity_size': int(largest_size),
        'members': members,
        'records': out,
        'read_only': True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'audit_largest_entity_10.json'
    path.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    print(json.dumps(report, indent=2, default=str))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
