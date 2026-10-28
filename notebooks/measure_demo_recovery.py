from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import ENTITY_MAP_PATH, PROCESSED_DATA_PATH
from src import registry


def main() -> None:
    batch3 = [b for b in registry.load()["batches"] if b["file"] == "batch_0003.csv"]
    if not batch3:
        raise SystemExit("batch_0003.csv is not registered")
    first = batch3[0]["record_id_range"][0]

    records = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id", "customer_id"])
    entities = pd.read_parquet(ENTITY_MAP_PATH, columns=["record_id", "entity_id"])
    merged = records.merge(entities, on="record_id")

    demo = merged[merged["record_id"] >= first]
    old = merged[merged["record_id"] < first]

    # Satu entity per customer_id pada data LAMA menjadi jawaban acuan.
    reference = old.groupby("customer_id")["entity_id"].first()
    expected = demo["customer_id"].map(reference)
    known = int(expected.notna().sum())
    demo_known = demo[expected.notna()]
    same = int((demo_known["entity_id"] == expected[expected.notna()]).sum())

    size = pd.read_parquet(ENTITY_MAP_PATH)
    print(f"demo rows: {len(demo):,} (first id {first})")
    print(f"customer_id with an old-data partner: {known:,}")
    print(f"recovered into the source entity: {same:,} / {known:,}")
    if known:
        print(f"recovery rate: {100.0 * same / known:.2f}%")
    print(f"entities in entity_map: {size['entity_id'].nunique():,}")


if __name__ == "__main__":
    main()