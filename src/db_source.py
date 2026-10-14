"""Read-only database source for the dedup pipeline.

Why DuckDB: it is already a transitive dependency of Splink (src/incremental.py
imports duckdb.connect()), so adding a database connection brings no new
package. A local .duckdb file opens read-only; a remote Postgres/MySQL/SQLite
is attached through DuckDB's scanner extensions, which are fetched on first
use and need network access once.

The connector only ever runs SELECT. It never issues write SQL, so a read-only
database account is enough and a bug here cannot damage the source system.

Column contract: the table is expected to expose the same source column names
the CSV path uses (the values in config.COLUMN_MAP). `device_id` is accepted
because config.DEVICE_ID_ALIASES already maps it to `device_id(s)`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb
import pandas as pd

from .config import PROJECT_ROOT

WATERMARK_PATH = PROJECT_ROOT / "data" / "processed" / "db_watermark.json"
WATERMARK_COLUMN = "updated_at"


def _apply_column_map(df: pd.DataFrame) -> pd.DataFrame:
    """Rename DB columns to the names the pipeline expects (config.DB_COLUMN_MAP).

    A database column named `first_nm` would otherwise be invisible to the
    pipeline, which looks for `first_name` — the batch standardizes but never
    links, with no error. Renaming here keeps the translation at the connector,
    so standardize and the blocking rules never need to know the DB's naming.
    """
    from .config import DB_COLUMN_MAP

    if not DB_COLUMN_MAP:
        return df
    rename = {db_name: pipe_name for db_name, pipe_name in DB_COLUMN_MAP.items() if db_name in df.columns}
    if rename:

        targets = list(rename.values())
        dupes = {t for t in targets if targets.count(t) > 1}
        if dupes:
            raise SystemExit(
                f"DB_COLUMN_MAP maps more than one column to {sorted(dupes)}. "
                "Each pipeline column can only come from one DB column — fix "
                "src/config.py."
            )
        df = df.rename(columns=rename)
    return df


def _normalize_dates(df: pd.DataFrame, exclude: set[str] | None = None) -> pd.DataFrame:
    """Convert DATE/datetime columns to ISO date strings.

    DuckDB returns a DATE column as datetime64 with a 00:00:00 time part.
    standardize.normalize_date regex-matches the whole value against
    ^\\d{1,4}[-/.]\\d{1,2}\\2\\d{1,4}$, so the trailing " 00:00:00" breaks the
    match and every date silently becomes None. Trimming to the date part here
    keeps the connector inside the pipeline's contract (string dates) without
    touching standardize.

    `exclude` names columns to leave at full timestamp precision — the
    watermark column, whose time-of-day is what makes an incremental pull
    correct. Trimming it to a date would drop every same-day update.
    """
    exclude = exclude or set()
    for col in df.columns:
        if col in exclude:
            continue
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.date.map(
                lambda v: v.isoformat() if v is not None and not pd.isna(v) else None
            )
    return df


def connect(source: str) -> duckdb.DuckDBPyConnection:
    """Open a read-only connection.

    `source` is a path to a .duckdb file, or a connection string for a remote
    database (postgres://..., mysql://..., sqlite://...).
    """
    if "://" not in source:
        return duckdb.connect(source, read_only=True)

    con = duckdb.connect(":memory:")
    scheme = source.split("://", 1)[0]

    con.execute(f"INSTALL {scheme}_scanner; LOAD {scheme}_scanner;")
    con.execute(f"ATTACH '{source}' AS src (TYPE {scheme}, READ_ONLY);")
    return con


def _ref(con: duckdb.DuckDBPyConnection, source: str, table: str) -> str:
    """Table reference: schema-qualified for a remote attach, plain for a file."""
    return f"src.{table}" if "://" in source else table


def _columns(con: duckdb.DuckDBPyConnection, source: str, table: str) -> list[str]:
    ref = _ref(con, source, table)
    return [r[0] for r in con.execute(f"SELECT * FROM {ref} LIMIT 0").description]


def _parse_watermark(value: str | dict | None) -> tuple[str | None, str | None]:
    """Watermark bisa string lama atau dict baru {updated_at, last_pk}."""
    if value is None:
        return None, None
    if isinstance(value, dict):
        return value.get("updated_at"), value.get("last_pk")
    return str(value), None


def fetch(
    source: str,
    table: str,
    watermark: str | dict | None = None,
    watermark_column: str = WATERMARK_COLUMN,
) -> pd.DataFrame:
    """Read rows as a DataFrame using the same column names the CSV path uses.

    Ketika watermark diberikan dan tabel memiliki kolom tersebut, hanya baris
    setelahnya yang diambil. Watermark baru menyimpan (updated_at, last_pk)
    sehingga baris dengan timestamp yang sama tetapi pk lebih besar tidak
    terlewat — celah G1: sebelumnya '>' ketat membuat 43 baris bertimestamp
    kembar berisiko hilang jika insert baru memakai detik yang sama.
    """
    con = connect(source)
    try:
        ref = _ref(con, source, table)
        cols = _columns(con, source, table)
        if watermark is not None and watermark_column in cols:
            wm_time, wm_pk = _parse_watermark(watermark)
            has_pk = "customer_pk" in cols
            if wm_time is not None and has_pk and wm_pk is not None:
                sql = (
                    f'SELECT * FROM {ref} WHERE ("{watermark_column}" > ? '
                    f'OR ("{watermark_column}" = ? AND "customer_pk"::VARCHAR > ?)) '
                    f'ORDER BY "{watermark_column}", "customer_pk"'
                )
                frame = con.execute(sql, [wm_time, wm_time, str(wm_pk)]).df()
            elif wm_time is not None:
                sql = (
                    f'SELECT * FROM {ref} WHERE "{watermark_column}" > ? '
                    f'ORDER BY "{watermark_column}"'
                )
                frame = con.execute(sql, [wm_time]).df()
            else:
                frame = con.execute(f"SELECT * FROM {ref}").df()
        else:
            frame = con.execute(f"SELECT * FROM {ref}").df()
        frame = _normalize_dates(frame, exclude={watermark_column})
        return _apply_column_map(frame)
    finally:
        con.close()


def latest_watermark(
    source: str, table: str, watermark_column: str = WATERMARK_COLUMN
) -> str | None:
    """Highest watermark value in the table, or None when the column is absent."""
    con = connect(source)
    try:
        if watermark_column not in _columns(con, source, table):
            return None
        ref = _ref(con, source, table)
        row = con.execute(f'SELECT MAX("{watermark_column}") FROM {ref}').fetchone()
        return None if row is None or row[0] is None else str(row[0])
    finally:
        con.close()


def _key(source: str, table: str) -> str:
    return f"{source}::{table}"


def read_watermark(source: str, table: str) -> str | dict | None:
    """Last exported watermark for this source, so a re-run can resume."""
    if not WATERMARK_PATH.exists():
        return None
    data = json.loads(WATERMARK_PATH.read_text(encoding="utf-8"))
    return data.get(_key(source, table))


def write_watermark(source: str, table: str, value: str | dict) -> None:
    """Persist the watermark. Written through a temp file so a crash mid-write
    cannot leave a truncated JSON that a later run would misread.

    `value` could be a plain timestamp (legacy callers) or a dict
    `{"updated_at": ..., "last_pk": ...}` written by db_refresh / job_run.
    The dict form is what closes the G1 gap: rows that share the watermark
    timestamp but carry a larger customer_pk are still fetched.
    """
    WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.loads(WATERMARK_PATH.read_text(encoding="utf-8"))
        if WATERMARK_PATH.exists()
        else {}
    )
    data[_key(source, table)] = value
    tmp = WATERMARK_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, WATERMARK_PATH)
