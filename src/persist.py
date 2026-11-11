"""Satu jalur simpan: PostgreSQL adalah sumber kebenaran.

Pipeline memanggil `persist_pipeline()` setelah artefak staging di-commit.
Semua penulisan idempoten (upsert), jadi menjalankan ulang tidak menggandakan
baris. File parquet tetap ditulis sebagai cache/fallback, bukan sumber utama.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    COLUMN_MAP,
    ENTITY_MAP_PATH,
    LABELS_DIR,
    MASTER_PATH,
    PROCESSED_DATA_PATH,
    predictions_path,
)
from .db import get_connection
from .provenance import current_run_info

GOLD_PATH = LABELS_DIR / "gold_labels.csv"
PAIR_SCORE_COLUMNS = (
    "match_probability",
    "match_weight",
    "decision",
    "business_rule",
    "blocking_rule",
    "gamma_name",
    "gamma_contact",
    "gamma_location",
    "gamma_dob",
)


def _py(value):
    """Ubah tipe pandas/numpy menjadi tipe Python yang diterima psycopg2."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (list, tuple, set, np.ndarray)):
        return [str(v) for v in list(value) if not _is_na(v)]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def _is_na(value) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _table_columns(table_name: str) -> tuple[str, ...]:
    schema, _, table = table_name.rpartition(".")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema or "public", table),
        )
        return tuple(row[0] for row in cur.fetchall())


def _prepare(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """Hanya kirim kolom yang benar-benar ada di tabel tujuan."""
    allowed = set(_table_columns(table_name))
    cols = [c for c in df.columns if c in allowed]
    if not cols:
        raise ValueError(f"Tidak ada kolom yang cocok dengan {table_name}")
    return df[cols].copy()


def _upsert(
    df: pd.DataFrame,
    table_name: str,
    key: str | tuple[str, ...],
    update: bool = True,
    chunk: int = 2000,
) -> int:
    """INSERT ... ON CONFLICT (key) DO UPDATE. Aman dijalankan berulang."""
    from psycopg2.extras import execute_values

    if df.empty:
        return 0
    frame = _prepare(df, table_name)
    keys = (key,) if isinstance(key, str) else tuple(key)
    cols = list(frame.columns)
    schema, _, table = table_name.rpartition(".")
    qualified = f'"{schema}"."{table}"' if schema else f'"{table}"'
    col_sql = ", ".join(f'"{c}"' for c in cols)
    key_sql = ", ".join(f'"{c}"' for c in keys)
    updatable = [c for c in cols if c not in keys]
    if update and updatable:
        action = "DO UPDATE SET " + ", ".join(
            f'"{c}" = EXCLUDED."{c}"' for c in updatable
        )
    else:
        action = "DO NOTHING"

    rows = [tuple(_py(v) for v in row) for row in frame.itertuples(index=False)]
    written = 0
    with get_connection() as conn, conn.cursor() as cur:
        for start in range(0, len(rows), chunk):
            batch = rows[start : start + chunk]
            execute_values(
                cur,
                f"INSERT INTO {qualified} ({col_sql}) VALUES %s "
                f"ON CONFLICT ({key_sql}) {action}",
                batch,
                page_size=len(batch),
            )
            written += len(batch)
    return written


# --- satu tabel, satu fungsi -------------------------------------------------


def persist_processed(df: pd.DataFrame, run_id: str) -> int:
    if df.empty:
        return 0
    keep = [
        "record_id", "customer_id", "source",
        "first_name_std", "last_name_std", "email_std", "phone_std",
        "address_std", "city_std", "state_std", "country_std", "dob_std",
    ]
    frame = df[[c for c in keep if c in df.columns]].copy()
    frame["record_id"] = frame["record_id"].astype(str)
    # konversi dob lokal dd/mm/YYYY ke Python date sebelum masuk DB
    if "dob_std" in frame.columns:
        frame["dob_std"] = pd.to_datetime(
            frame["dob_std"], dayfirst=True, errors="coerce"
        ).dt.date
    return _upsert(frame, "splink_data.processed_customers", "record_id")


def persist_pairs(df: pd.DataFrame, run_id: str, scope: str) -> int:
    if df.empty:
        return 0
    frame = df.copy()
    frame["record_id_l"] = frame["record_id_l"].astype(str)
    frame["record_id_r"] = frame["record_id_r"].astype(str)

    swap = frame["record_id_l"] > frame["record_id_r"]
    if swap.any():
        left = frame.loc[swap, "record_id_l"].copy()
        frame.loc[swap, "record_id_l"] = frame.loc[swap, "record_id_r"]
        frame.loc[swap, "record_id_r"] = left
        for col in PAIR_SCORE_COLUMNS:
            mirrored = f"{col}_l"
            if mirrored in frame.columns:
                tmp = frame.loc[swap, f"{col}_l"].copy()
                frame.loc[swap, f"{col}_l"] = frame.loc[swap, f"{col}_r"]
                frame.loc[swap, f"{col}_r"] = tmp

    keep = ["record_id_l", "record_id_r", *PAIR_SCORE_COLUMNS]
    frame = frame[[c for c in keep if c in frame.columns]].copy()
    frame["pipeline_run_id"] = run_id
    frame["source_scope"] = scope
    frame = frame.drop_duplicates(["record_id_l", "record_id_r"], keep="last")
    return _upsert(frame, "splink_data.dedup_outputs", ("record_id_l", "record_id_r"))


def persist_entity_map(df: pd.DataFrame, run_id: str) -> int:
    if df.empty:
        return 0
    frame = df[["record_id", "entity_id"]].copy()
    frame["record_id"] = frame["record_id"].astype(str)
    frame["entity_id"] = frame["entity_id"].astype(str)
    return _upsert(frame, "splink_data.entity_map", "record_id")


def persist_membership(
    processed: pd.DataFrame, entity_map: pd.DataFrame, run_id: str, model_version: str | None
) -> int:
    if processed.empty or entity_map.empty:
        return 0
    frame = entity_map[["record_id", "entity_id"]].copy()
    extra = processed[
        [c for c in ("record_id", "customer_id", "source") if c in processed.columns]
    ].copy()
    frame = frame.merge(extra, on="record_id", how="left")
    frame["model_version"] = model_version
    frame["pipeline_run_id"] = run_id
    return _upsert(frame, "splink_data.entity_membership", "record_id")


def persist_conflicts(master: pd.DataFrame, run_id: str) -> int:
    if master.empty or "conflicted_fields" not in master.columns:
        return 0
    rows: list[tuple[str, str]] = []
    for entity_id, fields in zip(master["entity_id"], master["conflicted_fields"]):
        values = fields if hasattr(fields, "__len__") and not isinstance(fields, str) else []
        for field in values:
            rows.append((str(entity_id), str(field)))
    if not rows:
        return 0

    entity_ids = sorted({row[0] for row in rows})
    with get_connection() as conn, conn.cursor() as cur:
        for start in range(0, len(entity_ids), 1000):
            cur.execute(
                "DELETE FROM splink_data.entity_conflict "
                "WHERE status = 'OPEN' AND entity_id = ANY(%s)",
                (entity_ids[start : start + 1000],),
            )
        from psycopg2.extras import execute_values

        execute_values(
            cur,
            "INSERT INTO splink_data.entity_conflict (entity_id, field_name, value, status) "
            "VALUES %s",
            [(eid, field, None, "OPEN") for eid, field in rows],
        )
    return len(rows)


def _master_plain(master: pd.DataFrame) -> pd.DataFrame:
    frame = master.copy()
    rename = {c: c[len("master_") :] for c in frame.columns if c.startswith("master_")}
    frame = frame.rename(columns=rename)
    if "resolution_status" not in frame.columns:
        conflicts = frame.get("conflicted_fields")
        frame["resolution_status"] = [
            "CONFLICTED" if (hasattr(v, "__len__") and not isinstance(v, str) and len(v)) else "CONFIRMED"
            for v in (conflicts if conflicts is not None else [None] * len(frame))
        ]
    return frame


def persist_master(master: pd.DataFrame, run_id: str, scope: str, model_version: str | None) -> int:
    if master.empty:
        return 0
    frame = _master_plain(master)
    keep = [
        "entity_id", "first_name", "last_name", "email", "phone", "address",
        "city", "state", "country", "dob", "resolution_status",
    ]
    frame = frame[[c for c in keep if c in frame.columns]].copy()
    frame["model_version"] = model_version
    frame["pipeline_run_id"] = run_id
    frame["source_scope"] = scope
    return _upsert(frame, "splink_data.master_customer_current", "entity_id")


def persist_snapshot(master: pd.DataFrame, meta: dict, run_id: str) -> int:
    """Simpan riwayat sekali per pipeline_run_id (bukan setiap batch)."""
    if master.empty:
        return 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM splink_data.master_customer_snapshot "
            "WHERE pipeline_run_id = %s LIMIT 1",
            (run_id,),
        )
        if cur.fetchone():
            return 0
    from .export import save_snapshot

    return save_snapshot(_master_plain(master), metadata=meta)


def persist_gold() -> int:
    if not GOLD_PATH.exists() or GOLD_PATH.stat().st_size == 0:
        return 0
    frame = pd.read_csv(GOLD_PATH, sep=None, engine="python")
    if not {"record_id_l", "record_id_r"} <= set(frame.columns):
        return 0
    keep = [
        "record_id_l", "record_id_r", "label", "stratum",
        "match_probability", "reviewer", "reviewer_note",
    ]
    frame = frame[[c for c in keep if c in frame.columns]].copy()
    frame["record_id_l"] = frame["record_id_l"].astype(str)
    frame["record_id_r"] = frame["record_id_r"].astype(str)
    frame["label"] = frame["label"].map(
        lambda v: "no_match" if str(v).strip().lower() in {"no_match", "no match", "non_match"} else str(v).strip().lower()
    )
    frame = frame[frame["label"].isin(["match", "no_match"])]
    if frame.empty:
        return 0
    frame = frame.drop_duplicates(["record_id_l", "record_id_r"], keep="last")
    return _upsert(frame, "splink_data.gold_labels", ("record_id_l", "record_id_r"))


def persist_raw_csv(path: str | Path) -> int:
    """Salin data mentah batch ke splink_data.customers."""
    path = Path(path)
    if not path.exists():
        return 0
    try:
        raw = pd.read_csv(path, sep=None, engine="python", dtype=str)
    except Exception:
        return 0
    raw = raw.rename(columns={src: dst for dst, src in COLUMN_MAP.items() if src in raw.columns})
    if "customer_id" not in raw.columns:
        return 0
    if "phone_number" in raw.columns:
        raw = raw.rename(columns={"phone_number": "phone"})
    keep = [
        "customer_id", "first_name", "last_name", "email", "phone",
        "address", "city", "state", "country", "dob",
    ]
    frame = raw[[c for c in keep if c in raw.columns]].copy()
    frame = frame.dropna(subset=["customer_id"]).drop_duplicates("customer_id", keep="last")
    # konversi dob lokal dd/mm/YYYY ke Python date sebelum masuk DB
    if "dob" in frame.columns:
        frame["dob"] = pd.to_datetime(
            frame["dob"], dayfirst=True, errors="coerce"
        ).dt.date
    return _upsert(frame, "splink_data.customers", "customer_id")


def update_master_row(entity_id: str, values: dict[str, str]) -> int:
    """Koreksi manual dari halaman Daftar Customer."""
    field_map = {
        "master_first_name_std": "first_name",
        "master_last_name_std": "last_name",
        "master_email_std": "email",
        "master_phone_std": "phone",
        "master_address_std": "address",
        "master_city_std": "city",
        "master_state_std": "state",
        "master_country_std": "country",
        "master_dob_std": "dob",
    }
    mapping = {
        field_map[key]: value
        for key, value in values.items()
        if key in field_map
    }
    if not mapping:
        return 0
    if "dob" in mapping:
        mapping["dob"] = pd.to_datetime(mapping["dob"], errors="coerce", dayfirst=True).date()
    sets = ", ".join(f'"{col}" = %s' for col in mapping)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE splink_data.master_customer_current SET {sets}, "
            "updated_at = CURRENT_TIMESTAMP WHERE entity_id = %s",
            [*mapping.values(), entity_id],
        )
        return cur.rowcount


# --- orkestrator -------------------------------------------------------------


def persist_pipeline(full: bool = True, snapshot: bool = True) -> dict[str, int]:
    """Tulis semua artefak hasil run ke PostgreSQL. Idempoten."""
    scope = "full" if full else "sample"
    meta = current_run_info()
    run_id = str(meta["pipeline_run_id"])
    model_version = meta.get("model_version")

    processed = pd.read_parquet(PROCESSED_DATA_PATH)
    pairs = pd.read_parquet(predictions_path(full=full))
    entity_map = pd.read_parquet(ENTITY_MAP_PATH)
    master = pd.read_parquet(MASTER_PATH)

    result = {
        "processed_customers": persist_processed(processed, run_id),
        "dedup_outputs": persist_pairs(pairs, run_id, scope),
        "entity_map": persist_entity_map(entity_map, run_id),
        "entity_membership": persist_membership(processed, entity_map, run_id, model_version),
        "entity_conflict": persist_conflicts(master, run_id),
        "master_customer_current": persist_master(master, run_id, scope, model_version),
        "gold_labels": persist_gold(),
    }
    if snapshot:
        result["master_customer_snapshot"] = persist_snapshot(master, meta, run_id)
    return result


def print_result(result: dict[str, int]) -> None:
    for table, rows in result.items():
        print(f"  {table:28s} {rows:>8,} baris")