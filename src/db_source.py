

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


def list_tables(source: str) -> list[str]:

    con = connect(source)
    try:
        schema_prefix = "src." if "://" in source else ""
        rows = con.execute(
            f"SELECT table_name FROM {schema_prefix}information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'sqlite_master')"
        ).fetchall()
        return sorted(r[0] for r in rows)
    finally:
        con.close()


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


def _check_table(source: str, table: str, date_order: str | None = None) -> dict:

    from .config import COLUMN_MAP, DEVICE_ID_ALIASES
    from .validate_upload import (
        blocking_source_columns,
        optional_source_columns,
        shape_findings,
        shape_report,
        suggest_column_mappings,
    )

    con = connect(source)
    try:
        cols = _columns(con, source, table)
    finally:
        con.close()

    blocking = blocking_source_columns()
    optional = optional_source_columns()
    mapped = {v: k for k, v in COLUMN_MAP.items()}
    unmapped = [c for c in cols if c not in mapped]
    missing_blocking = sorted(blocking - set(cols))
    missing_optional = sorted(optional - set(cols))


    frame = fetch(source, table)
    sample = frame.head(500)
    date_ev = {}
    if date_order:
        date_ev = {"dob": {"applied_order": date_order}}
    shape = shape_report(sample, date_ev)
    shape_blocking, shape_warnings = shape_findings(shape)

    return {
        "source": source,
        "table": table,
        "columns": cols,
        "n_columns": len(cols),
        "mapped_columns": {c: mapped[c] for c in cols if c in mapped},
        "unmapped_columns": unmapped,
        "missing_blocking": missing_blocking,
        "missing_optional": missing_optional,
        "optional_present": sorted(set(cols) & optional),
        "device_alias_present": sorted(set(cols) & set(DEVICE_ID_ALIASES)),
        "shape": shape,
        "shape_blocking": shape_blocking,
        "shape_warnings": shape_warnings,
        "column_suggestions": suggest_column_mappings(cols),
    }


def _print_check(report: dict) -> None:
    print(f"Source: {report['source']}")
    print(f"Table : {report['table']} ({report['n_columns']} columns)")
    print()
    print("Columns:")
    for c in report["columns"]:
        tag = "mapped" if c in report["mapped_columns"] else "unmapped"
        print(f"  {c:24s} {tag}")
    if report["unmapped_columns"]:
        print()
        print("Unmapped — not in COLUMN_MAP, so the pipeline cannot use them:")
        for c in report["unmapped_columns"]:
            print(f"  - {c}")
    print()
    print("Blocking columns present:")
    for c in sorted(report["columns"]):
        if c in report["mapped_columns"]:
            print(f"  + {c} -> {report['mapped_columns'][c]}")
    if report["missing_blocking"]:
        print(f"  MISSING: {report['missing_blocking']}")
    print()
    print("Optional columns present:")
    for c in report["optional_present"]:
        print(f"  ~ {c}")
    if report["missing_optional"]:
        print(f"  absent: {report['missing_optional']}")
    if report["device_alias_present"]:
        print(f"  device alias: {report['device_alias_present']}")
    print()
    print("Shape / type (500-row sample; blank is missing data, not a failure):")
    for canonical, info in report["shape"].items():
        if canonical == "customer_pk":
            verdict = "OK unique" if info["unique_ok"] else (
                f"NOT UNIQUE ({info['duplicated']:,} dup) -> update-in-place unsafe"
            )
            print(f"  {info['column']:14s} {info['non_blank']:,} rows -> {verdict}")
        elif info.get("measurable") is False:
            print(f"  {info['column']:14s} not checked — {info['reason']}")
        else:
            print(
                f"  {info['column']:14s} {info['shaped']:,}/{info['non_blank']:,} "
                f"valid ({100.0 - info['unshaped_pct']:.2f}%), "
                f"{info['blank']:,} blank"
            )
            if info["samples"]:
                print(f"                   e.g. {info['samples'][:3]}")
    if report["shape_blocking"]:
        print()
        print("BLOCKING — the table is not usable as-is:")
        for b in report["shape_blocking"]:
            print(f"  x {b}")
    if report["shape_warnings"]:
        print()
        print("Warnings:")
        for w in report["shape_warnings"]:
            print(f"  ! {w}")
    if report["shape_blocking"]:
        raise SystemExit(1)


def read_watermark(source: str, table: str) -> str | dict | None:
    """Last exported watermark for this source, so a re-run can resume."""
    if not WATERMARK_PATH.exists():
        return None
    data = json.loads(WATERMARK_PATH.read_text(encoding="utf-8"))
    return data.get(_key(source, table))


def write_watermark(source: str, table: str, value: str | dict) -> None:

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


def _key(source: str, table: str) -> str:
    return f"{source}::{table}"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Inspect a database source without writing anything."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "List columns, show which are unmapped, which blocking columns are "
            "missing, and whether the identity fields have the right shape. "
            "Read-only: no CSV written, no batch registered."
        ),
    )
    parser.add_argument("--source", required=True, help="DSN or path to a .duckdb file.")
    parser.add_argument("--table", required=True, help="Table or view to inspect.")
    parser.add_argument(
        "--date-order",
        choices=["auto", "dmy", "mdy"],
        default="auto",
        help="Day/month order for ambiguous dates, so the shape check can run.",
    )
    args = parser.parse_args()

    if not args.check:

        parser.print_help()
        raise SystemExit(0)

    order = None if args.date_order == "auto" else args.date_order
    report = _check_table(args.source, args.table, date_order=order)
    _print_check(report)


if __name__ == "__main__":
    main()
