"""Export deduplication results to CSV and PostgreSQL."""

from __future__ import annotations

import io
import json
import os
import uuid
from datetime import datetime, timezone
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
    """Insert rows into an existing `table_name`; never create or alter tables.

    Re-running with the same keys raises psycopg2.errors.UniqueViolation;
    the caller decides whether that is an error or expected.
    """
    import psycopg2
    from psycopg2.extras import execute_values

    if df.empty:
        return 0

    schema, _, table = table_name.rpartition(".")
    if not table or not table_name.replace("_", "").replace(".", "").isalnum():
        raise ValueError("Nama tabel harus berupa schema.table atau table yang valid.")
    qualified = f'"{schema}"."{table}"' if schema else f'"{table}"'
    col_names = ", ".join(f'"{c}"' for c in df.columns)
    if {"entity_id", "resolution_status"} <= set(df.columns):
        insert = f"INSERT INTO {qualified} ({col_names}) VALUES %s ON CONFLICT (entity_id) DO UPDATE SET " + ", ".join(
            f'"{c}" = EXCLUDED."{c}"' for c in df.columns if c != "entity_id"
        )
    else:
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
            cur.execute(
                "SELECT to_regclass(%s)",
                (f"{schema}.{table}" if schema else table,),
            )
            if cur.fetchone()[0] is None:
                raise ValueError(f"Tabel tujuan tidak ditemukan: {table_name}")
            rows = [tuple(_clean(v) for v in r) for r in df.itertuples(index=False)]
            execute_values(cur, insert, rows)
        return len(df)
    finally:
        conn.close()


def _as_date(value):
        """Convert a value to a Python date, returning None for NA."""
        if value is None:
            return None
        try:
            return pd.to_datetime(value, errors="coerce").date()
        except (TypeError, ValueError):
            return None


def save_snapshot(
    master_export_df: pd.DataFrame,
    metadata: dict | None = None,
    table_current: str = "splink_data.master_customer_current",
    table_snapshot: str = "splink_data.master_customer_snapshot",
) -> int:
    """Menyimpan snapshot dari master_customer_current ke tabel master_customer_snapshot.

    Setiap pemanggilan menghasilkan snapshot_id baru, sehingga riwayat export terpisah.
    Metadata opsional berisi model_version, pipeline_run_id, source_scope.
    Jika tidak diberikan, nilai default digunakan.
    """

    import psycopg2
    from psycopg2.extras import execute_values

    if master_export_df.empty:
        return 0

    if metadata is None:
        metadata = {
            "model_version": "unknown",
            "pipeline_run_id": "run-unknown",
            "source_scope": "full",
        }

    # Pastikan kolom yang dibutuhkan ada di dataframe
    needed = ["entity_id", "first_name_std", "last_name_std", "email_std", "phone_std",
              "address_std", "city_std", "state_std", "country_std", "dob_std", "resolution_status"]
    for c in needed:
        if c not in master_export_df.columns:
            master_export_df[c] = None

    schema, _, snap_table = table_snapshot.rpartition(".")
    qualified = f'"{schema}"."{snap_table}"' if schema else f'"{snap_table}"'

    # Bangun rows
    rows = []
    for _, row in master_export_df.iterrows():
        snapshot_id = str(uuid.uuid4())
        rows.append((
            snapshot_id,
            str(row["entity_id"]),
            str(row["first_name_std"]) if pd.notna(row.get("first_name_std")) else None,
            str(row["last_name_std"]) if pd.notna(row.get("last_name_std")) else None,
            str(row["email_std"]) if pd.notna(row.get("email_std")) else None,
            str(row["phone_std"]) if pd.notna(row.get("phone_std")) else None,
            str(row["address_std"]) if pd.notna(row.get("address_std")) else None,
            str(row["city_std"]) if pd.notna(row.get("city_std")) else None,
            str(row["state_std"]) if pd.notna(row.get("state_std")) else None,
            str(row["country_std"]) if pd.notna(row.get("country_std")) else None,
            _as_date(row.get("dob_std")),
            str(row["resolution_status"]) if "resolution_status" in master_export_df.columns else "CONFIRMED",
            metadata.get("model_version", "unknown"),
            metadata.get("pipeline_run_id", "run-unknown"),
            metadata.get("source_scope", "full"),
            datetime.now(timezone.utc),  # exported_at
        ))

    create = f'''
        CREATE TABLE IF NOT EXISTS {qualified} (
            snapshot_id UUID PRIMARY KEY,
            entity_id VARCHAR(255) NOT NULL,
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            email VARCHAR(255),
            phone VARCHAR(50),
            address VARCHAR(500),
            city VARCHAR(100),
            state VARCHAR(100),
            country VARCHAR(100),
            dob DATE,
            resolution_status VARCHAR(30) NOT NULL,
            model_version VARCHAR(100),
            pipeline_run_id VARCHAR(100),
            source_scope VARCHAR(20),
            exported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    '''

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
            execute_values(
                cur,
                f"INSERT INTO {qualified} "
                "(snapshot_id, entity_id, first_name, last_name, email, phone, address, "
                "city, state, country, dob, resolution_status, model_version, "
                "pipeline_run_id, source_scope, exported_at) "
                "VALUES %s",
                rows,
            )
        return len(rows)
    finally:
        conn.close()
