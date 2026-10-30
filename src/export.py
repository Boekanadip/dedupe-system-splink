"""Export deduplication results to CSV and PostgreSQL."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def _clean(value):
    """Convert pandas NA to None; leave everything else untouched."""
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):  # arrays/lists: isna is ambiguous
        return value


def export_to_csv(df: pd.DataFrame, output_path: str | Path) -> Path:
    """Write DataFrame to UTF-8 CSV. Returns the written path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def export_to_json(df: pd.DataFrame, output_path: str | Path) -> Path:
    """Write DataFrame to JSON records. Returns the written path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(path, orient="records", indent=2, force_ascii=False)
    return path


def csv_bytes(df: pd.DataFrame) -> bytes:
    """Serialize DataFrame to CSV bytes for HTTP download."""
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def save_to_database(df: pd.DataFrame, table_name: str = "splink_data.dedup_outputs") -> int:
    """Insert rows into `table_name`, creating it from df's columns if absent.

    Re-running with the same keys raises psycopg2.errors.UniqueViolation;
    the caller decides whether that is an error or expected.

    ponytail: CREATE TABLE from df dtypes assumes numeric/BIGINT and text
    otherwise; add explicit dtype mapping when non-text columns beyond
    match_probability appear.
    """
    import psycopg2
    from psycopg2.extras import execute_values

    if df.empty:
        return 0

    schema, _, table = table_name.rpartition(".")
    qualified = f"{schema}.{table}" if schema else table

    def col_type(s: pd.Series) -> str:
        if pd.api.types.is_float_dtype(s):
            return "DOUBLE PRECISION"
        if pd.api.types.is_integer_dtype(s):
            return "BIGINT"
        return "TEXT"

    cols = ", ".join(f'"{c}" {col_type(df[c])}' for c in df.columns)
    col_names = ", ".join(f'"{c}"' for c in df.columns)
    pk = ""
    if {"record_id_l", "record_id_r"} <= set(df.columns):
        pk = f", CONSTRAINT {table}_pk PRIMARY KEY (record_id_l, record_id_r)"
    create = f"CREATE TABLE IF NOT EXISTS {qualified} ({cols}{pk});"
    insert = f"INSERT INTO {qualified} ({col_names}) VALUES %s"

    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "crm"),
        user=os.getenv("POSTGRES_USER", "crm_user"),
        password=os.getenv("POSTGRES_PASSWORD", "crm_password_2026"),
    )
    try:
        with conn, conn.cursor() as cur:
            cur.execute(create)
            rows = [tuple(_clean(v) for v in r) for r in df.itertuples(index=False)]
            execute_values(cur, insert, rows)
        return len(df)
    finally:
        conn.close()
