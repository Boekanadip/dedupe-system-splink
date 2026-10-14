#!/usr/bin/env python
"""Generate a synthetic DuckDB file that satisfies the pipeline's column contract.

The output is a local .duckdb file with a `crm_customers` table. It contains
deterministic duplicates and near-duplicates so the dedup pipeline actually
finds matches — useful for a demo without real data.

Run:
    python scripts/make_synthetic_db.py --rows 2000 --out data/synthetic/crm.duckdb

Then export to the pipeline:
    python -m src.db_export --source data/synthetic/crm.duckdb --table crm_customers --watermark
    python -m src.incremental --stage
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure `src` package is importable even when this script is run directly.
_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

import duckdb
import pandas as pd

# Deterministic seed so re-runs produce the same data — helps debugging.
random.seed(42)

# Small name pools to create natural duplicates and near-duplicates.
FIRST = [
    "Andi", "Budi", "Citra", "Dewi", "Eka", "Fajar", "Gita", "Hadi",
    "Intan", "Joko", "Kartika", "Lestari", "Maya", "Nanda", "Oki", "Putri",
]
LAST = [
    "Santoso", "Wijaya", "Hidayat", "Prasetyo", "Saputra", "Kusuma",
    "Nugroho", "Setiawan", "Permadi", "Handoko", "Gunawan", "Halim",
]
DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "example.com", "company.co.id"]
CITIES = ["Jakarta", "Bandung", "Surabaya", "Medan", "Semarang", "Makassar", "Palembang", "Depok"]
STATES = ["DKI Jakarta", "Jawa Barat", "Jawa Timur", "Sumatera Utara", "Jawa Tengah", "Sulawesi Selatan", "Sumatera Selatan", "Jawa Barat"]
COUNTRIES = ["Indonesia"]
GENDERS = ["M", "F", "L", "P"]


def pick_name() -> tuple[str, str]:
    return random.choice(FIRST), random.choice(LAST)


def make_email(first: str, last: str) -> str:
    local = f"{first.lower()}.{last.lower()}{random.randint(1, 999)}"
    return f"{local}@{random.choice(DOMAINS)}"


def make_phone() -> str:
    body = "".join(str(random.randint(0, 9)) for _ in range(9))
    prefix = random.choice(["+62 8", "08"])
    return f"{prefix}{body[:3]} {body[3:6]} {body[6:]}"


def make_address() -> str:
    nums = random.randint(1, 999)
    street = random.choice(["Jl. Merdeka", "Jl. Sudirman", "Jl. Gatot Subroto", "Jl. Thamrin", "Jl. Asia Afrika"])
    return f"{street} No. {nums}"


def make_dob() -> date:
    years_ago = random.randint(18, 75)
    base = date.today().replace(year=date.today().year - years_ago)
    return base - timedelta(days=random.randint(0, 364))


def make_signup() -> date:
    return date.today() - timedelta(days=random.randint(1, 1825))


def make_device(idx: int) -> str:
    """Device id unik per customer_pk — satu orang, satu device.

    Versi lama memakai random.randint(1, 200) sehingga 75 baris berbagi
    200 slot dan device yang sama muncul pada orang yang jelas berbeda
    (0 dari 7 field identik). Itu melanggar asumsi device_truth_pairs
    yang memperlakukan device_id sama = satu orang, dan membuat
    clusters_recover_device_truth gagal: model BENAR menolak pasangan
    yang bedanya jelas, tapi test menghitungnya sebagai false negative.
    """
    return f"dev_{idx:04d}"


def make_source() -> str:
    return random.choice(["web", "mobile", "pos", "call_center", "import"])


def make_updated_at(base: datetime, idx: int, dup_factor: int = 50) -> datetime:
    offset = idx if idx % dup_factor else 0
    return base - timedelta(minutes=offset)


def build_rows(n: int, dup_every: int = 50, near_dup_every: int = 75) -> list[dict]:
    """Generate N rows with deterministic duplicates and near-duplicates.

    - Every `dup_every`-th row is an EXACT copy of the previous one.
    - Every `near_dup_every`-th row copies the previous row but with a
      typo in phone (last digit changed) or email (local part changed).
    """
    rows = []
    now = datetime.now()

    for i in range(1, n + 1):
        if i % dup_every == 0 and rows:
            # Exact duplicate of previous
            prev = rows[-1].copy()
            prev["customer_pk"] = i
            prev["customer_id"] = f"C{prev['customer_id'][1:]}"
            prev["updated_at"] = make_updated_at(now, i)
            rows.append(prev)
            continue

        if i % near_dup_every == 0 and rows:
            # Near-duplicate: same person, typo in phone or email
            prev = rows[-1].copy()
            prev["customer_pk"] = i
            prev["customer_id"] = f"C{prev['customer_id'][1:]}"
            if random.random() < 0.5:
                prev["phone_number"] = prev["phone_number"][:-1] + str(random.randint(0, 9))
            else:
                local, domain = prev["email"].split("@")
                prev["email"] = f"{local}x@{domain}"
            prev["updated_at"] = make_updated_at(now, i)
            rows.append(prev)
            continue

        first, last = pick_name()
        rows.append({
            "customer_pk": i,
            "customer_id": f"C{i:06d}",
            "first_name": first,
            "last_name": last,
            "email": make_email(first, last),
            "phone_number": make_phone(),
            "gender": random.choice(GENDERS),
            "dob": make_dob().isoformat(),
            "signup_date": make_signup().isoformat(),
            "address": make_address(),
            "city": random.choice(CITIES),
            "state": random.choice(STATES),
            "country": random.choice(COUNTRIES),
            "device_id": make_device(i),
            "source": make_source(),
            "updated_at": make_updated_at(now, i),
        })

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic CRM DuckDB.")
    parser.add_argument("--rows", type=int, default=2000, help="Number of rows to generate.")
    parser.add_argument("--out", default="data/synthetic/crm.duckdb", help="Output .duckdb path.")
    parser.add_argument("--table", default="crm_customers", help="Table name.")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.rows:,} synthetic rows...")
    rows = build_rows(args.rows)
    df = pd.DataFrame(rows)

    # Verify column contract against the pipeline's COLUMN_MAP
    from src.config import COLUMN_MAP, DEVICE_ID_ALIASES

    # A DB column is acceptable if it matches a COLUMN_MAP value, OR matches a
    # DEVICE_ID_ALIASES name (the DB convention for the device column).
    csv_sources = set(COLUMN_MAP.values())
    acceptable = csv_sources | set(DEVICE_ID_ALIASES)
    missing = (csv_sources - set(df.columns) - set(DEVICE_ID_ALIASES))
    extra = set(df.columns) - acceptable - {"customer_pk", "updated_at"}
    if missing:
        print(f"WARNING: missing expected columns: {missing}")
    if extra:
        print(f"INFO: extra columns (ignored by pipeline): {extra}")

    con = duckdb.connect(str(out_path))
    try:
        con.execute(f"DROP TABLE IF EXISTS {args.table}")
        con.execute(f"""
            CREATE TABLE {args.table} (
                customer_pk     BIGINT PRIMARY KEY,
                customer_id     VARCHAR(64),
                first_name      VARCHAR(128) NOT NULL,
                last_name       VARCHAR(128) NOT NULL,
                email           VARCHAR(255),
                phone_number    VARCHAR(32),
                gender          VARCHAR(16),
                dob             DATE,
                signup_date     DATE,
                address         VARCHAR(255),
                city            VARCHAR(128),
                state           VARCHAR(64),
                country         VARCHAR(64),
                device_id       VARCHAR(255),
                source          VARCHAR(64),
                updated_at      TIMESTAMP NOT NULL
            )
        """)
        con.register("df", df)
        con.execute(f"INSERT INTO {args.table} SELECT * FROM df")
        count = con.execute(f"SELECT count(*) FROM {args.table}").fetchone()[0]
        print(f"Created {out_path} with table '{args.table}': {count:,} rows")
        print(f"Column names: {', '.join(df.columns)}")
        print("\nTo feed the pipeline:")
        print(f"  python -m src.db_export --source {out_path} --table {args.table} --watermark")
        print(f"  python -m src.incremental --stage")
    finally:
        con.close()


if __name__ == "__main__":
    main()