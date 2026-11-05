"""Fill the normalized resolution tables from pipeline artifacts.

Writes:
  splink_data.entity_membership      one row per record
  splink_data.entity_conflict        one row per conflicting field value (OPEN)
  splink_data.master_customer_current one row per entity

Safe to re-run: membership and master are upserted, open conflicts are rebuilt
per entity while RESOLVED/IGNORED rows are preserved.

    python scripts/sync_resolution_outputs.py --dry-run
    python scripts/sync_resolution_outputs.py --apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from src.config import (
    ENTITY_MAP_PATH,
    MASTER_PATH,
    PROCESSED_DATA_PATH,
    read_meta,
)
from src.db import DATABASE_URL
from src.master_record import MASTER_FIELDS

MASTER_COLUMNS = {
    "first_name_std": "first_name",
    "last_name_std": "last_name",
    "email_std": "email",
    "phone_std": "phone",
    "address_std": "address",
    "city_std": "city",
    "state_std": "state",
    "country_std": "country",
    "dob_std": "dob",
}


def _clean(value):
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value


def _as_date(value):
    value = _clean(value)
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def load_frames():
    entity_map = pd.read_parquet(ENTITY_MAP_PATH)
    master = pd.read_parquet(MASTER_PATH)
    standardized = pd.read_parquet(PROCESSED_DATA_PATH)
    return entity_map, master, standardized


def build_membership(entity_map: pd.DataFrame, standardized: pd.DataFrame) -> pd.DataFrame:
    columns = [c for c in ("record_id", "customer_id", "source") if c in standardized.columns]
    frame = entity_map[["record_id", "entity_id"]].merge(
        standardized[columns], on="record_id", how="left"
    )
    for column in ("customer_id", "source"):
        if column not in frame.columns:
            frame[column] = None
    return frame[["entity_id", "record_id", "customer_id", "source"]]


def build_conflicts(entity_map: pd.DataFrame, standardized: pd.DataFrame) -> pd.DataFrame:
    fields = [c for c in MASTER_FIELDS if c in standardized.columns]
    frame = entity_map[["record_id", "entity_id"]].merge(
        standardized[["record_id", *fields]], on="record_id", how="left"
    )
    long = frame.melt(
        id_vars=["entity_id"],
        value_vars=fields,
        var_name="field_name",
        value_name="value",
    ).dropna(subset=["value"])
    distinct = long.drop_duplicates(["entity_id", "field_name", "value"])

    counts = distinct.groupby(["entity_id", "field_name"])["value"].transform("size")
    conflicts = distinct[counts > 1].sort_values(["entity_id", "field_name", "value"])
    return conflicts[["entity_id", "field_name", "value"]]


def build_current(master: pd.DataFrame, conflicts: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame({"entity_id": master["entity_id"]})
    for source, target in MASTER_COLUMNS.items():
        frame[target] = master[source] if source in master.columns else None
    conflicted = set(conflicts["entity_id"].unique())
    frame["resolution_status"] = frame["entity_id"].map(
        lambda entity: "CONFLICTED" if entity in conflicted else "CONFIRMED"
    )
    return frame


def _insert_conflicts(cur, conflicts: pd.DataFrame, metadata: dict) -> int:
    if conflicts.empty:
        return 0
    # Keep manual decisions (RESOLVED/IGNORED); rebuild every open finding.
    cur.execute("DELETE FROM splink_data.entity_conflict WHERE status = 'OPEN'")
    rows = [
        (entity, field, value, "OPEN", None, None)
        for entity, field, value in conflicts.itertuples(index=False)
    ]
    execute_values(
        cur,
        "INSERT INTO splink_data.entity_conflict "
        "(entity_id, field_name, value, status, reviewer, reviewed_at) "
        "VALUES %s",
        rows,
    )
    return len(rows)


def _insert_membership(cur, membership: pd.DataFrame, metadata: dict) -> int:
    rows = [
        (e, r, c, s, metadata["model_version"], metadata["pipeline_run_id"])
        for e, r, c, s in membership.itertuples(index=False)
    ]
    cur.execute(
        "DELETE FROM splink_data.entity_membership WHERE record_id <> ALL(%s)",
        ([r[1] for r in rows],),
    )
    execute_values(
        cur,
        "INSERT INTO splink_data.entity_membership "
        "(entity_id, record_id, customer_id, source, model_version, pipeline_run_id) "
        "VALUES %s ON CONFLICT (record_id) DO UPDATE SET "
        "entity_id = EXCLUDED.entity_id, customer_id = EXCLUDED.customer_id, "
        "source = EXCLUDED.source, model_version = EXCLUDED.model_version, "
        "pipeline_run_id = EXCLUDED.pipeline_run_id, assigned_at = CURRENT_TIMESTAMP",
        rows,
    )
    return len(rows)


def _insert_current(cur, current: pd.DataFrame, metadata: dict) -> int:
    rows = [
        (
            e, first, last, email, phone, address, city, state, country, dob,
            status, metadata["model_version"], metadata["pipeline_run_id"],
            metadata["source_scope"],
        )
        for (e, first, last, email, phone, address, city, state, country, dob, status)
        in current.itertuples(index=False)
    ]
    # "current" berarti cermin terbaru: entity yang hilang setelah rebuild dibuang.
    cur.execute(
        "DELETE FROM splink_data.master_customer_current WHERE entity_id <> ALL(%s)",
        ([r[0] for r in rows],),
    )
    execute_values(
        cur,
        "INSERT INTO splink_data.master_customer_current "
        "(entity_id, first_name, last_name, email, phone, address, city, state, "
        "country, dob, resolution_status, model_version, pipeline_run_id, source_scope) "
        "VALUES %s ON CONFLICT (entity_id) DO UPDATE SET "
        "first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name, "
        "email = EXCLUDED.email, phone = EXCLUDED.phone, address = EXCLUDED.address, "
        "city = EXCLUDED.city, state = EXCLUDED.state, country = EXCLUDED.country, "
        "dob = EXCLUDED.dob, resolution_status = EXCLUDED.resolution_status, "
        "model_version = EXCLUDED.model_version, "
        "pipeline_run_id = EXCLUDED.pipeline_run_id, "
        "source_scope = EXCLUDED.source_scope, exported_at = CURRENT_TIMESTAMP, "
        "updated_at = CURRENT_TIMESTAMP",
        rows,
    )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Tulis ke database.")
    parser.add_argument("--model-version", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)

    meta = read_meta(MASTER_PATH) or read_meta(ENTITY_MAP_PATH)
    metadata = {
        "model_version": args.model_version or meta.get("model_version") or "unknown",
        "pipeline_run_id": args.run_id
        or f"sync-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
        "source_scope": meta.get("scope") or "full",
    }

    entity_map, master, standardized = load_frames()
    membership = build_membership(entity_map, standardized)
    conflicts = build_conflicts(entity_map, standardized)
    current = build_current(master, conflicts)
    for column in ("dob",):
        current[column] = current[column].map(_as_date)

    print(f"membership : {len(membership):,} baris")
    print(f"conflicts  : {len(conflicts):,} baris "
          f"({conflicts['entity_id'].nunique():,} entity)")
    print(f"current    : {len(current):,} entity "
          f"({int((current['resolution_status'] == 'CONFLICTED').sum()):,} CONFLICTED)")
    print(f"metadata   : {metadata}")

    if not args.apply:
        print("\nMode uji. Tambahkan --apply untuk menulis ke database.")
        return 0

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            print(f"membership : {_insert_membership(cur, membership, metadata):,} baris")
            print(f"conflicts  : {_insert_conflicts(cur, conflicts, metadata):,} baris")
            print(f"current    : {_insert_current(cur, current, metadata):,} entity")
    finally:
        conn.close()
    print("Selesai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
