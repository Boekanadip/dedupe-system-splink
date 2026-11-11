"""Baca data untuk UI: PostgreSQL dulu, parquet sebagai fallback.

Semua halaman Streamlit memakai modul ini. Baca disegel dengan cache TTL 60s
agar rerun Streamlit tidak query berulang. `source_badge()` dipakai UI untuk
menunjukkan data diambil dari database atau file.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from .config import ENTITY_MAP_PATH, MASTER_PATH, PROCESSED_DATA_PATH, predictions_path
from .db import get_connection

CACHE_TTL = 60
_CACHE: dict[tuple, tuple[float, Any]] = {}


def _cache(key, compute):
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    value = compute()
    _CACHE[key] = (now, value)
    return value


def clear_cache() -> None:
    _CACHE.clear()


def _query(sql: str, params: tuple | None = None) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def table_rows(table: str) -> int:
    return _cache(("rows", table), lambda: int(_query(f"SELECT COUNT(*) AS n FROM {table}")["n"][0]))


def source_badge() -> str:
    """Label sumber data untuk UI."""
    try:
        if table_rows("splink_data.master_customer_current") > 0:
            return "database"
    except Exception:
        pass
    return "file"


def _fallback_parquet(path, columns, limit) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    _columns = [c for c in (columns or []) if c is not None]
    frame = pd.read_parquet(path, columns=_columns or None)
    return frame.head(limit) if limit else frame


def read_processed(columns: list[str] | None = None, limit: int | None = None) -> pd.DataFrame:
    """Baris terstandardisasi, satu baris per record."""

    def compute():
        try:
            sql = "SELECT * FROM splink_data.processed_customers"
            if limit:
                sql += f" LIMIT {int(limit)}"
            frame = _query(sql)
            if not frame.empty:
                return frame
        except Exception:
            pass
        return _fallback_parquet(PROCESSED_DATA_PATH, columns, limit)

    return _cache(("processed", tuple(columns or []), limit), compute).copy()


def read_pairs(
    columns: list[str] | None = None,
    decision: str | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Hasil skor pasangan. `decision` menyaring MATCH/REVIEW/NON_MATCH."""

    def compute():
        try:
            if table_rows("splink_data.dedup_outputs") > 0:
                # columns=None → ambil semua kolom (page explain memakai gamma_*).
                select = (
                    ", ".join(f'"{c}"' for c in columns)
                    if columns
                    else "*"
                )
                sql = f"SELECT {select} FROM splink_data.dedup_outputs"
                params: tuple = ()
                if decision:
                    sql += " WHERE decision = %s"
                    params = (decision,)
                if limit:
                    sql += f" LIMIT {int(limit)}"
                return _query(sql, params)
        except Exception:
            pass
        frame = _fallback_parquet(predictions_path(full=True), columns, limit)
        if decision and not frame.empty and "decision" in frame.columns:
            frame = frame[frame["decision"] == decision]
        return frame

    return _cache(("pairs", tuple(columns or []), decision, limit), compute).copy()


def read_entity_map(columns: list[str] | None = None, limit: int | None = None) -> pd.DataFrame:
    """Peta record_id -> entity_id."""

    def compute():
        try:
            if table_rows("splink_data.entity_map") > 0:
                sql = "SELECT * FROM splink_data.entity_map"
                if limit:
                    sql += f" LIMIT {int(limit)}"
                return _query(sql)
        except Exception:
            pass
        return _fallback_parquet(ENTITY_MAP_PATH, columns, limit)

    return _cache(("entity_map", limit), compute).copy()


def read_conflicted_count() -> int:
    """Jumlah entity yang masih punya field konflik."""
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM ("
                "  SELECT entity_id FROM splink_data.entity_conflict "
                "  WHERE status = 'OPEN' GROUP BY entity_id"
                ") AS x"
            )
            return int(cur.fetchone()[0])
    except Exception:
        return 0

def read_master(limit: int | None = None) -> pd.DataFrame:
    """Master customer. Anggota dan konflik dibaca dari tabel relasinya.

    ponytail: agregasi array cocok untuk 45k entity. Untuk jutaan entity,
    ganti halaman ke query terpaginasi (LIMIT + OFFSET).
    """

    def compute():
        try:
            if table_rows("splink_data.master_customer_current") > 0:
                sql = """
                    SELECT
                        m.entity_id, m.first_name, m.last_name, m.email, m.phone,
                        m.address, m.city, m.state, m.country, m.dob,
                        m.resolution_status, m.model_version, m.pipeline_run_id,
                        m.source_scope, m.exported_at,
                        COALESCE(x.record_count, 0) AS record_count,
                        COALESCE(x.record_ids, ARRAY[]::text[]) AS record_ids,
                        COALESCE(x.customer_ids, ARRAY[]::text[]) AS customer_ids,
                        COALESCE(x.sources, ARRAY[]::text[]) AS sources,
                        COALESCE(c.conflicted_fields, ARRAY[]::text[]) AS conflicted_fields
                    FROM splink_data.master_customer_current AS m
                    LEFT JOIN (
                        SELECT entity_id,
                               COUNT(*) AS record_count,
                               ARRAY_AGG(record_id) AS record_ids,
                               ARRAY_AGG(DISTINCT COALESCE(customer_id, '')) AS customer_ids,
                               ARRAY_AGG(DISTINCT COALESCE(source, '')) AS sources
                        FROM splink_data.entity_membership
                        GROUP BY entity_id
                    ) x USING (entity_id)
                    LEFT JOIN (
                        SELECT entity_id,
                               ARRAY_AGG(DISTINCT field_name) AS conflicted_fields
                        FROM splink_data.entity_conflict
                        WHERE status = 'OPEN'
                        GROUP BY entity_id
                    ) c USING (entity_id)
                    ORDER BY record_count DESC, entity_id
                """
                if limit:
                    sql += f" LIMIT {int(limit)}"
                frame = _query(sql)
                if not frame.empty:
                    rename = {
                        c: f"master_{c}"
                        for c in ("first_name", "last_name", "email", "phone",
                                  "address", "city", "state", "country", "dob")
                    }
                    return frame.rename(columns=rename)
        except Exception:
            pass
        return _fallback_parquet(MASTER_PATH, None, limit)

    return _cache(("master", limit), compute).copy()
