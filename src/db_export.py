"""Export a database table to a registered CSV batch.

This is the bridge that lets the existing pipeline consume a database without
changing Splink, blocking, or standardize: the table is read read-only, written
to data/raw/batch_NNNN.csv, and registered exactly like an uploaded file.
Everything downstream (validate, standardize, incremental) is unchanged.

Usage:
    python -m src.db_export --source data/synthetic/crm.duckdb --table crm_customers
    python -m src.db_export --source ... --table ... --watermark
    python -m src.db_export --source ... --table ... --out data/raw/batch_0009.csv

--watermark resumes from the last exported updated_at, so repeated calls fetch
only rows that changed. The watermark is advanced only after a successful
export, so a failed run re-fetches the same rows instead of skipping them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import registry
from .db_source import (
    WATERMARK_COLUMN,
    fetch,
    latest_watermark,
    read_watermark,
    write_watermark,
)

RAW_DIR = registry.RAW_DIR


def register_frame(frame: pd.DataFrame, out: str | None = None) -> dict:
    """Write a DataFrame to a batch CSV and register it.

    Shared by export_batch (full table fetch) and db_refresh (insert-only
    subset), so both go through the same already-registered guard and the same
    record_id allocation.
    """
    if frame.empty:
        return {"status": "noop", "rows": 0}

    dest = Path(out) if out else _next_batch_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # ';' matches the dataset convention; validate_upload.read_csv_any accepts both.
    frame.to_csv(dest, sep=";", index=False)

    digest = registry.sha256_of(dest)
    existing = next(
        (b for b in registry.load()["batches"] if b["sha256"] == digest), None
    )
    if existing is not None:
        dest.unlink(missing_ok=True)
        return {
            "status": "already_registered",
            "rows": existing["rows"],
            "csv": str(RAW_DIR / existing["file"]),
            "batch_id": existing["batch_id"],
            "batch_file": existing["file"],
            "record_id_range": existing["record_id_range"],
            "message": (
                f"Rows already registered as batch {existing['batch_id']} "
                f"({existing['file']}). Continuing from the existing batch."
            ),
        }

    try:
        batch = registry.register(dest, len(frame))
    except SystemExit as exc:
        dest.unlink(missing_ok=True)
        raise SystemExit(f"Registration refused, CSV removed: {exc}") from None
    return {
        "status": "exported",
        "rows": len(frame),
        "columns": list(frame.columns),
        "csv": str(dest),
        "batch_id": batch["batch_id"],
        "batch_file": batch["file"],
        "record_id_range": batch["record_id_range"],
    }


def export_batch(
    source: str,
    table: str,
    use_watermark: bool = False,
    out: str | None = None,
    defer_watermark: bool = False,
) -> dict:
    """Fetch a table and register it as a batch. Returns a result dict.

    By default the watermark advances after a successful registration, so a
    failed export re-fetches the same rows instead of skipping them.

    `defer_watermark=True` holds the advance back and returns `latest_mark`
    instead. job_run uses this so the watermark only moves once the WHOLE job
    (export + incremental) succeeds — otherwise a failed incremental would
    consume the rows and leave the batch orphaned, unreachable by a re-run.
    """
    watermark = read_watermark(source, table) if use_watermark else None
    frame = fetch(source, table, watermark=watermark)
    if frame.empty:
        return {
            "status": "noop",
            "rows": 0,
            "message": "0 rows to export. Nothing written, watermark unchanged.",
        }

    result = register_frame(frame, out)

    advanced = None
    if use_watermark and not defer_watermark and result["status"] == "exported":
        advanced = latest_watermark(source, table)
        if advanced is not None:
            write_watermark(source, table, {"updated_at": advanced})

    result["watermark"] = advanced
    result["latest_mark"] = latest_watermark(source, table) if use_watermark else None
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a database table to a registered CSV batch (read-only)."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Path to a .duckdb file, or a connection string (postgres://...).",
    )
    parser.add_argument("--table", required=True, help="Table or view to read.")
    parser.add_argument(
        "--out",
        default=None,
        help="CSV destination. Default: data/raw/batch_NNNN.csv (next free number).",
    )
    parser.add_argument(
        "--watermark",
        action="store_true",
        help=(
            f"Read only rows newer than the last exported {WATERMARK_COLUMN}. "
            "Advances the watermark after a successful export."
        ),
    )
    parser.add_argument(
        "--date-order",
        choices=["auto", "dmy", "mdy"],
        default="auto",
        help="Day/month order for ambiguous dates, same flag as src.run_all.",
    )
    args = parser.parse_args()

    if args.watermark and read_watermark(args.source, args.table) is None:
        print(f"No saved watermark yet — full fetch from {args.table}.")

    result = export_batch(args.source, args.table, args.watermark, args.out)

    if result["status"] == "noop":
        print(result["message"])
        return

    print(f"Fetched {result['rows']:,} rows x {len(result['columns'])} columns")
    print(f"Columns: {', '.join(result['columns'])}")
    print(f"Written: {result['csv']}")
    print(
        f"Registered batch {result['batch_id']}: {result['batch_file']} "
        f"({result['rows']:,} rows, {result['record_id_range'][0]}..{result['record_id_range'][1]})"
    )
    if args.watermark:
        if result["watermark"] is None:
            print(f"Table has no {WATERMARK_COLUMN} — watermark not advanced.")
        else:
            print(f"Watermark advanced to {result['watermark']}")

    print("\nNext: review and run the pipeline")
    cmd = [sys.executable, "-m", "src.incremental", "--stage"]
    if args.date_order != "auto":
        cmd += ["--date-order", args.date_order]
    print("  " + " ".join(cmd))


def _next_batch_path() -> Path:
    raw_dir = registry.RAW_DIR
    taken = {b["file"] for b in registry.load()["batches"]}
    number = max((b["batch_id"] for b in registry.load()["batches"]), default=0) + 1
    while (raw_dir / f"batch_{number:04d}.csv").exists() or f"batch_{number:04d}.csv" in taken:
        number += 1
    return raw_dir / f"batch_{number:04d}.csv"


if __name__ == "__main__":
    main()
