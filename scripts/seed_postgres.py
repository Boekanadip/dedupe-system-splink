from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb

DUCK = PROJECT_ROOT / "data" / "synthetic" / "crm.duckdb"
OUT = PROJECT_ROOT / "scripts" / "seed_customers_v2.sql"
TABLE = "customers_v2"
LIMIT = 1000


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, float) and value != value:  # NaN
        return "NULL"
    # datetime/date harus ikut di-quote: kolom dob/signup_date/updated_at di
    # DDL diturunkan sebagai VARCHAR (pandas dtype object -> VARCHAR setelah
    # normalize), tapi nilai keluar dari pandas sebagai datetime64. Tanpa
    # kutip Postgres membaca "1995-06-22 00:00:00" sebagai literal dan
    # melempar syntax error at or near "00".
    if isinstance(value, (datetime, date)):
        return "'" + str(value).replace("'", "''") + "'"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a Postgres seed .sql from the local DuckDB."
    )
    parser.add_argument("--limit", type=int, default=LIMIT, help="Rows to copy.")
    parser.add_argument("--table", default=TABLE, help="Target table name.")
    parser.add_argument("--out", default=str(OUT), help="Output .sql path.")
    parser.add_argument("--source", default=str(DUCK), help="Source .duckdb path.")
    args = parser.parse_args()

    duck = duckdb.connect(args.source, read_only=True)
    try:
        tables = [r[0] for r in duck.execute("SHOW TABLES").fetchall()]
        if not tables:
            print(f"ERROR: {DUCK.name} tidak berisi tabel")
            return 1
        source = tables[0]
        frame = duck.execute(f"SELECT * FROM {source} LIMIT {args.limit}").df()
    finally:
        duck.close()

    print(f"Source table : {source}")
    print(f"Rows copied  : {len(frame):,} (limit {args.limit})")

    # tipe kolom diturunkan dari pandas dtype, bukan ditebak nama kolom
    pg_types = {
        "object": "VARCHAR",
        "bool": "BOOLEAN",
        "int64": "BIGINT",
        "float64": "DOUBLE PRECISION",
        "datetime64[ns]": "TIMESTAMP",
    }
    cols_sql = ",\n".join(
        f"    \"{c}\" {pg_types.get(str(frame[c].dtype), 'VARCHAR')}" for c in frame.columns
    )

    out = Path(args.out)
    lines = [
        f"-- Di-generate scripts/seed_postgres.py dari {source} ({len(frame):,} baris)",
        f"DROP TABLE IF EXISTS {args.table};",
        f"CREATE TABLE {args.table} (\n{cols_sql}\n);",
        "",
    ]
    rows = [
        "(" + ", ".join(_sql_literal(v) for v in row) + ")"
        for row in frame.itertuples(index=False, name=None)
    ]
    lines.append(f"INSERT INTO {args.table} VALUES\n" + ",\n".join(rows) + ";")
    lines.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")

    print(f"Written      : {out}")
    print(f"\nJalankan:\n  Get-Content {out} | docker exec -i crm-pg psql -U crm_owner -d crm")
    print("Lalu buka tab Database di app.py — tabel sudah bisa dipilih.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
