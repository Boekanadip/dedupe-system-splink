"""Validate an uploaded batch before it is registered (PRD FR-01, MASTER_CONTEXT §7).

An upload that reaches standardize() half-valid produces a dataset that cannot be
blocked, and the failure surfaces later as a MISSING COLUMN from Splink — after
the bad data has already been written and registered. This refuses it first.

Rules
Required : first_name, last_name, and at least one of email / phone_number.
Also required: every source column behind an ACTIVE blocking rule in
           BENCHMARK_RULES. Derived from config, not hardcoded, because
           standardize() refuses a dataset whose blocking keys are missing — a
           validator that only warned would promise acceptance the pipeline then
           revokes after the batch was already registered.
Helpful  : columns that improve recall but block nothing (dob, address and city
           are blocking keys today; signup_date and country are not).
Optional : everything else in COLUMN_MAP.

Column names come from COLUMN_MAP and nowhere else. Guessing a name here would
make the validator agree with a typo in the pipeline.

Two things it also reports, because they are decisions and not errors:
- delimiter and encoding actually used (the development files are ';' while an
  export from a comma-decimal locale is also ';' with comma decimals in numbers)
- date-format evidence per date column, so a UI can ask the day/month question
  with the detected order already offered as the default
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BENCHMARK_RULES, COLUMN_MAP, OUTPUT_DIR

REPORT_PATH = OUTPUT_DIR / "upload_validation_report.json"

REQUIRED_COLUMNS = ["first_name", "last_name"]
ONE_OF = [("email", "phone")]


def blocking_source_columns() -> set[str]:
    """Source columns whose _std form is used by an active blocking rule.

    Derived from BENCHMARK_RULES so this validator and src.standardize can never
    disagree about what a batch must contain.
    """
    keys = {col for _, cols in BENCHMARK_RULES for col in cols}
    # A blocking key such as 'first_name_std' or the derived 'first_name_std_pre3'
    # both point back at the source column 'first_name'.
    derived = {k[:-4] for k in keys if k.endswith("_std")}
    derived |= {k.split("_std_")[0] for k in keys if "_std_" in k}
    return {COLUMN_MAP[c] for c in COLUMN_MAP if c in derived}


# Columns that improve linking but break nothing if absent. Deliberately derived
# from the full column map, not a hand-written list.
def optional_source_columns() -> set[str]:
    return set(COLUMN_MAP.values()) - blocking_source_columns() - {
        COLUMN_MAP[c] for c in REQUIRED_COLUMNS
    } - {COLUMN_MAP[c] for c, _ in ONE_OF}

DELIMITERS = {";": ";", ",": ",", "\t": "\t", "|": "|"}


def read_csv_any(path: Path) -> tuple[pd.DataFrame, dict]:
    """Read a CSV whose delimiter and encoding are not guaranteed.

    load_raw() assumes ';'. A client export is just as likely to be comma
    separated, and reading the wrong one silently folds every column into a
    single header.
    """
    raw = None
    encoding_used = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            raw = path.read_text(encoding=encoding)
            encoding_used = encoding
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise SystemExit(f"{path.name}: could not decode as utf-8 or latin-1")

    first_line = raw.split("\n", 1)[0]
    # Prefer a delimiter that actually splits the header into several fields.
    best = max(DELIMITERS, key=lambda d: first_line.count(d))
    if first_line.count(best) == 0:
        # Last resort: let pandas sniff.
        frame = pd.read_csv(path, sep=None, engine="python", low_memory=False)
        return frame, {
            "delimiter": "sniffed",
            "encoding": encoding_used,
            "note": "no delimiter found in the header; pandas sniffed the file",
        }

    frame = pd.read_csv(path, sep=best, low_memory=False)
    return frame, {"delimiter": DELIMITERS[best], "encoding": encoding_used}


def date_format_evidence(df: pd.DataFrame) -> dict:
    """Day/month evidence per date column, using the standardization parser."""
    from .standardize import detect_date_order

    out = {}
    for canonical in ("dob", "signup_date"):
        source = COLUMN_MAP[canonical]
        if source not in df.columns:
            continue
        order, evidence = detect_date_order(df[source])
        out[canonical] = {
            **evidence,
            "needs_answer": order is None,
            "question": (
                f"Apakah kolom {source} berisi tanggal dd/mm/YYYY atau mm/dd/YYYY?"
                if order is None
                else None
            ),
        }
    return out


def validate(df: pd.DataFrame) -> dict:
    """Return a report. `blocking` is a list of reasons the batch must be refused."""
    available = set(df.columns)
    blocking: list[str] = []
    warnings: list[str] = []

    missing_required = [c for c in REQUIRED_COLUMNS if COLUMN_MAP[c] not in available]
    if missing_required:
        blocking.append(
            "missing required column(s): "
            + ", ".join(f"{c} (expects '{COLUMN_MAP[c]}')" for c in missing_required)
        )

    present_contact = [c for c, _ in ONE_OF if COLUMN_MAP[c] in available]
    if not present_contact:
        blocking.append(
            "needs at least one contact column: "
            + " or ".join(f"'{COLUMN_MAP[c]}'" for c, _ in ONE_OF)
            + " — without email or phone there is no key the linker can use"
        )

    # Blocking keys must exist, or standardize() refuses the batch anyway. Caught
    # here so the upload is rejected before it is written and registered.
    needed = blocking_source_columns()
    missing_keys = sorted(needed - available)
    if missing_keys:
        blocking.append(
            "column(s) required by the active blocking rules are absent: "
            + ", ".join(missing_keys)
            + " — the batch would standardize but never link. Add them, or drop the "
            "rules that need them in BENCHMARK_RULES (src/config.py)."
        )

    missing_helpful = [c for c in sorted(optional_source_columns()) if c not in available]
    if missing_helpful:
        warnings.append(
            "optional column(s) absent: "
            + ", ".join(missing_helpful)
            + " — linking still runs; these only add evidence"
        )

    if len(df) == 0:
        blocking.append("the file has a header but no data rows")

    null_report = {}
    for canonical in REQUIRED_COLUMNS + [c for c, _ in ONE_OF]:
        source = COLUMN_MAP[canonical]
        if source in available:
            nulls = int(df[source].isna().sum() + (df[source].astype(str).str.strip() == "").sum())
            null_report[source] = {
                "null_pct": round(100.0 * nulls / len(df), 3) if len(df) else 0.0,
                "null_count": nulls,
            }
            if nulls == len(df) and len(df):
                blocking.append(f"column '{source}' is empty in every row")

    # device_ids_std holds a list per row, so hashing it for the duplicate check
    # raises "unhashable type". Duplicate detection runs on scalar columns only.
    scalar_columns = [c for c in df.columns if not _has_list_values(df[c])]

    return {
        "status": "rejected" if blocking else "accepted",
        "rows": len(df),
        "columns": len(df.columns),
        "available_columns": sorted(available),
        "blocking": blocking,
        "warnings": warnings,
        "null_profile": null_report,
        "exact_duplicate_rows": int(df.duplicated(subset=scalar_columns).sum())
        if len(df) and scalar_columns
        else 0,
        "duplicate_check_columns": len(scalar_columns),
        "date_formats": date_format_evidence(df),
    }


def _has_list_values(series: pd.Series, sample: int = 50) -> bool:
    """True when the first few values are list/array rather than scalars."""
    for value in series.head(sample):
        if isinstance(value, (list, tuple, set, np.ndarray)):
            return True
    return False


def validate_file(path: Path) -> tuple[dict, pd.DataFrame]:
    frame, source_info = read_csv_any(Path(path))
    report = validate(frame)
    report["file"] = {
        "name": Path(path).name,
        "delimiter": source_info["delimiter"],
        "encoding": source_info["encoding"],
        **({"note": source_info["note"]} if "note" in source_info else {}),
    }
    return report, frame


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an uploaded CSV before registering it as a batch."
    )
    parser.add_argument("path", help="CSV file to validate")
    parser.add_argument("--report", default=str(REPORT_PATH), help="Where to write the JSON report")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"{path} not found")

    report, _ = validate_file(path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")

    f = report["file"]
    print(f"File   : {f['name']}  (delimiter {f['delimiter']!r}, encoding {f['encoding']})")
    print(f"Shape  : {report['rows']:,} rows x {report['columns']} columns")
    print(f"Status : {report['status'].upper()}")

    if report["blocking"]:
        print("\nBLOCKING — the batch must not be registered:")
        for reason in report["blocking"]:
            print(f"  x {reason}")
    if report["warnings"]:
        print("\nWarnings — accepted, but they lower recall:")
        for reason in report["warnings"]:
            print(f"  ! {reason}")

    nulls = {k: v for k, v in report["null_profile"].items() if v["null_pct"] > 0}
    if nulls:
        print("\nNull profile:")
        for column, stats in nulls.items():
            print(f"  {column:16s} {stats['null_pct']:6.2f}% ({stats['null_count']:,})")
    if report["exact_duplicate_rows"]:
        print(f"\nExact duplicate rows within the upload: {report['exact_duplicate_rows']:,}")

    dates = report["date_formats"]
    if dates:
        print("\nDate format evidence:")
        for column, ev in dates.items():
            detail = (
                f"day>12 in {ev['day_gt_12']:,}, month>12 in {ev['month_gt_12']:,}, "
                f"ambiguous in {ev['ambiguous_rows']:,}"
            )
            if ev["needs_answer"]:
                print(f"  {column:14s} {detail} -> MUST ASK: {ev['question']}")
            else:
                print(f"  {column:14s} {detail} -> detected {ev['detected_order']}")

    print(f"\nSaved: {args.report}")
    raise SystemExit(1 if report["blocking"] else 0)


if __name__ == "__main__":
    main()
