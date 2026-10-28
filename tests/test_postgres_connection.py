
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os

DSN = os.environ.get(
    "TEST_PG_DSN", "postgres://crm_owner:devpassword@127.0.0.1:5432/crm"
)
TABLE = os.environ.get("TEST_PG_TABLE", "crm_customers")


def main() -> int:
    failures: list[str] = []

    # 1. connect via the same function the pipeline uses
    from src.db_source import _columns, connect, fetch

    con = connect(DSN)
    try:
        row = con.execute("SELECT 1").fetchone()
        assert row == (1,), f"unexpected SELECT 1 result: {row}"
        print(f"[ok] connect: {DSN}")

        # 2. table visible through the attached schema
        names = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM src.information_schema.tables "
                "WHERE table_schema='public'"
            ).fetchall()
        ]
        if TABLE not in names:
            failures.append(f"table {TABLE!r} not found; available: {names}")
        else:
            print(f"[ok] table visible: {TABLE} (public tables: {names})")
    finally:
        con.close()

    # 3. column contract: what the pipeline actually requires, per validate_upload
    from src.config import COLUMN_MAP, DEVICE_ID_ALIASES
    from src.validate_upload import blocking_source_columns

    con = connect(DSN)
    try:
        cols = set(_columns(con, DSN, TABLE))
    finally:
        con.close()

    required = {COLUMN_MAP[c] for c in ("first_name", "last_name")}
    one_of = {COLUMN_MAP[c] for c in ("email", "phone")}
    needed = required | one_of | blocking_source_columns()
    missing = sorted(needed - cols)
    if missing:
        failures.append(
            f"missing pipeline columns in {TABLE}: {missing} "
            "(set DB_COLUMN_MAP in src/config.py if the DB uses other names)"
        )
    else:
        print(f"[ok] column contract satisfied ({len(needed)} required names present)")

    # device_id(s) is optional but valuable; the DB may name it device_id
    if not ({"device_id(s)"} | set(DEVICE_ID_ALIASES)) & cols:
        print("[info] no device_id column — device-based verification unavailable")
    else:
        print("[ok] device column present")

    # 4. full fetch through db_source.fetch (same read path the export uses)
    frame = fetch(DSN, TABLE)
    if frame.empty:
        failures.append(f"{TABLE} fetched 0 rows")
    else:
        print(f"[ok] fetch: {len(frame):,} rows x {len(frame.columns)} cols")

    # 5. export registration path, without touching the real batch registry
    if failures:
        print("\nFAIL")
        for f in failures:
            print(f" - {f}")
        return 1

    print("\nPASS: PostgreSQL reachable via src.db_source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
