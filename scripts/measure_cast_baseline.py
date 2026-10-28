#!/usr/bin/env python3
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import COLUMN_MAP
from src.standardize import normalize_email, normalize_phone, normalize_date, detect_date_order
from src.db_source import fetch


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")  # simple RFC-ish


def measure_csv(path: Path) -> dict:
    from src.profiling import load_raw
    df = load_raw(path)
    return _measure_frame(df, f"csv:{path.name}")


def measure_db(source: str, table: str) -> dict:
    frame = fetch(source, table)
    return _measure_frame(frame, f"db:{source}::{table}")


def _measure_frame(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    out = {"source": label, "total_rows": n}

    # email
    src = COLUMN_MAP["email"]
    if src in df.columns:
        vals = df[src].dropna().astype(str)
        parseable = vals.map(lambda v: bool(EMAIL_RE.match(v.strip().lower())) if v.strip() else False)
        out["email"] = {
            "present": n,
            "non_null": int(vals.notna().sum()),
            "parseable": int(parseable.sum()),
            "parse_rate": round(parseable.mean() * 100, 2) if n else 0,
            "sample_unparseable": vals[~parseable].head(5).tolist(),
        }

    # phone
    src = COLUMN_MAP["phone"]
    if src in df.columns:
        vals = df[src].dropna().astype(str)
        digits = vals.map(lambda v: re.sub(r"\D", "", v.split("x")[0].strip()) if v.strip() else "")
        has_digits = digits.map(bool)
        out["phone"] = {
            "present": n,
            "non_null": int(vals.notna().sum()),
            "digit_only": int(has_digits.sum()),
            "digit_rate": round(has_digits.mean() * 100, 2) if n else 0,
            "sample_empty": vals[~has_digits].head(5).tolist(),
        }

    # dob
    src = COLUMN_MAP["dob"]
    if src in df.columns:
        vals = df[src].dropna().astype(str)
        # detect date_order untuk normalisasi
        order, _ = detect_date_order(vals)
        dayfirst = order == "dmy"
        parsed = vals.map(lambda v: normalize_date(v, dayfirst) is not None)
        out["dob"] = {
            "present": n,
            "non_null": int(vals.notna().sum()),
            "parsed": int(parsed.sum()),
            "parse_rate": round(parsed.mean() * 100, 2) if n else 0,
            "detected_order": order,
            "sample_unparsed": vals[~parsed].head(5).tolist(),
        }

    # customer_pk uniqueness
    if "customer_pk" in df.columns:
        pk = df["customer_pk"]
        unique = pk.nunique()
        total = pk.notna().sum()
        out["customer_pk"] = {
            "total": int(total),
            "unique": int(unique),
            "duplicate_count": int(total - unique),
            "uniqueness_rate": round(unique / total * 100, 2) if total else 100,
        }

    return out


def main():
    results = []

    # 1. CSV 50k (sample 5000 for speed, atau full kalau cepat)
    csv_path = PROJECT_ROOT / "data" / "raw" / "crm_50000_customers_dirty_v3.csv"
    if csv_path.exists():
        print(f"Measuring {csv_path.name}...", file=sys.stderr)
        results.append(measure_csv(csv_path))

    # 2. Postgres (if reachable)
    pg_source = "postgres://crm_owner:devpassword@127.0.0.1:5432/crm"
    try:
        print(f"Measuring Postgres crm_customers...", file=sys.stderr)
        results.append(measure_db(pg_source, "crm_customers"))
    except Exception as e:
        print(f"Postgres not reachable or error: {e}", file=sys.stderr)

    # 3. DuckDB synthetic (small)
    duckdb_path = PROJECT_ROOT / "data" / "synthetic" / "crm.duckdb"
    if duckdb_path.exists():
        try:
            print(f"Measuring DuckDB synthetic...", file=sys.stderr)
            results.append(measure_db(f"{duckdb_path}", "crm_customers"))
        except Exception as e:
            print(f"DuckDB error: {e}", file=sys.stderr)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()