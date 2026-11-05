"""Manual database migration runner.

Applies every *.sql file in docker/migrations in filename order, once each,
and records it in splink_data.schema_migrations. Nothing runs unless --apply
is passed.

    python scripts/migrate_db.py            # list pending migrations
    python scripts/migrate_db.py --apply    # execute pending migrations
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2

from src.db import DATABASE_URL

MIGRATIONS_DIR = PROJECT_ROOT / "docker" / "migrations"
TRACKING_TABLE = "splink_data.schema_migrations"


def _connect():
    return psycopg2.connect(DATABASE_URL)


def _applied(cur) -> dict[str, str]:
    cur.execute(
        "CREATE SCHEMA IF NOT EXISTS splink_data;"
        f"CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} ("
        "  filename TEXT PRIMARY KEY,"
        "  checksum TEXT NOT NULL,"
        "  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);"
    )
    cur.execute(f"SELECT filename, checksum FROM {TRACKING_TABLE}")
    return dict(cur.fetchall())


def _pending(cur) -> list[tuple[Path, str]]:
    done = _applied(cur)
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    out = []
    for path in files:
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name in done:
            if done[path.name] != checksum:
                print(f"WARNING: {path.name} berubah setelah diterapkan; tidak dijalankan ulang.")
            continue
        out.append((path, checksum))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Jalankan migration yang belum diterapkan.")
    args = parser.parse_args(argv)

    conn = _connect()
    try:
        with conn, conn.cursor() as cur:
            pending = _pending(cur)
            if not pending:
                print("Tidak ada migration baru.")
                return 0
            print(f"{len(pending)} migration belum diterapkan:")
            for path, _ in pending:
                print(f"  - {path.name}")
            if not args.apply:
                print("\nMode daftar saja. Tambahkan --apply untuk menjalankan.")
                return 0
            for path, checksum in pending:
                print(f"Applying {path.name} ...", end=" ")
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute(
                    f"INSERT INTO {TRACKING_TABLE} (filename, checksum) VALUES (%s, %s)",
                    (path.name, checksum),
                )
                print("OK")
    finally:
        conn.close()
    print("Selesai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
