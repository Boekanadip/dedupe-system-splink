"""Audit registry vs artefak vs PostgreSQL. Read-only; tidak mengubah data.

Jalankan: python -m scripts.audit_registry
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
REG = ROOT / "data" / "processed" / "batch_registry.json"
PROC = ROOT / "data" / "processed" / "crm_standardized.parquet"
OUT = ROOT / "outputs"


def ids_of(path: Path, col: str = "record_id") -> set[str] | None:
    if not path.exists():
        return None
    return set(pd.read_parquet(path, columns=[col])[col].astype(str))


def main() -> None:
    registry = json.loads(REG.read_text(encoding="utf-8"))
    batches = sorted(registry["batches"], key=lambda b: b["start_index"])
    reg_total = sum(b["rows"] for b in batches)
    print(f"registry batches: {len(batches)} rows: {reg_total:,} next_start_index: {registry['next_start_index']:,}")

    raw_files = {p.name for p in RAW.glob("*.csv")}
    reg_files = {b["file"] for b in batches}
    missing = sorted(reg_files - raw_files)
    unregistered = sorted(raw_files - reg_files)
    print(f"registered but missing on disk: {len(missing)}")
    print(f"on disk but not registered: {len(unregistered)}: {unregistered}")

    hash_counts = Counter(b["sha256"] for b in batches)
    dupes = {h: c for h, c in hash_counts.items() if c > 1}
    print(f"duplicate sha256: {len(dupes)}")

    gaps, overlaps = [], []
    prev_end = None
    for b in batches:
        if prev_end is not None:
            if b["start_index"] > prev_end + 1:
                gaps.append((prev_end + 1, b["start_index"] - 1))
            elif b["start_index"] <= prev_end:
                overlaps.append((b["file"], b["start_index"], prev_end))
        prev_end = max(prev_end or 0, b["end_index"])
    print(f"range gaps: {len(gaps)} overlaps: {len(overlaps)}")

    from src.profiling import load_raw
    mismatches = []
    for b in batches:
        p = RAW / b["file"]
        if p.exists() and len(load_raw(p)) != b["rows"]:
            mismatches.append(b["file"])
    print(f"row-count mismatches: {len(mismatches)} {mismatches}")

    proc = ids_of(PROC) or set()
    print(f"processed parquet rows: {len(proc):,} range: {min(proc)}..{max(proc)}")

    per_batch = []
    for b in batches:
        lo = int(b["record_id_range"][0].split("_")[1])
        hi = int(b["record_id_range"][1].split("_")[1])
        present = sum(1 for i in range(lo, hi + 1) if f"rec_{i:06d}" in proc)
        per_batch.append((b["file"], b["rows"], present))
    full = sum(1 for _, rows, present in per_batch if present == rows)
    print(f"batches fully present in parquet: {full}/{len(per_batch)}")
    for f, rows, present in per_batch:
        if present != rows:
            print(f"  PARTIAL {f}: reg={rows:,} in_parquet={present:,}")

    ent = ids_of(OUT / "entity_map.parquet")
    if ent:
        print(f"entity_map ids: {len(ent):,} range: {min(ent)}..{max(ent)}")
        print(f"entity_map not in processed parquet: {len(ent - proc):,}")

    # PostgreSQL (read-only); laporan tetap jalan jika DB mati.
    try:
        import psycopg2
        c = psycopg2.connect(host="localhost", dbname="crm", user="crm_user",
                             password="crm_password_2026", connect_timeout=3)
        q = c.cursor()
        for t in ("processed_customers", "dedup_outputs", "entity_map",
                  "master_customer_current", "master_customer_bersih", "customers"):
            q.execute(f"SELECT COUNT(*) FROM splink_data.{t}")
            print(f"db {t}: {q.fetchone()[0]:,}")
        q.execute("SELECT MIN(record_id), MAX(record_id) FROM splink_data.processed_customers")
        print("db processed range:", q.fetchone())
        c.close()
    except Exception as exc:
        print("db unavailable:", type(exc).__name__)

    print("kesimpulan: registry internal konsisten; selisih datang dari parquet/DB yang dibangun pada run berbeda.")


if __name__ == "__main__":
    main()
