from __future__ import annotations

import argparse
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import (
    BENCHMARK_RULES,
    COLUMN_MAP,
    DATE_ORDER,
    PROCESSED_DATA_PATH,
    RAW_DATA_PATH,
    SOURCE_RECORD_ID_COLUMN,
    write_meta,
)
from .profiling import load_raw

# Three numeric fields with ONE repeated separator. Kept strict on purpose: a
# loose pattern is how '1988-04-11' ends up read as 4 November.
NUMERIC_DATE = re.compile(r"^(\d{1,4})([-/.])(\d{1,2})\2(\d{1,4})$")


def normalize_text(value) -> str | None:
    if pd.isna(value):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s'’-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_name(value) -> str | None:
    return normalize_text(value)


def normalize_email(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().lower()
    return text or None


def normalize_phone(value) -> str | None:
    """Digits only, with the extension dropped.

    MEASURED on the 50k development file before this change: 29,966 of 50,000
    values carry an "xNNN" extension, and `re.sub(r"\D", "")` folded the
    extension into the key. '(449) 977-1729' and '449.977.1729x282' are the same
    number written by two systems, but they produced two different keys and so
    could never match each other.

    The extension is dropped, not the whole number: a shared switchboard with
    different extensions is still evidence of the same organisation, and the
    main line is the part a customer would recognise as their number.
    """
    if pd.isna(value):
        return None
    text = re.split(r"[xX]\s*\d+", str(value))[0]
    digits = re.sub(r"\D", "", text)
    return digits or None


def normalize_date(value, dayfirst: bool) -> str | None:
    """Parse one date to ISO, resolving day/month order explicitly.

    dayfirst is REQUIRED on purpose. The previous implementation tried %d/%m/%Y
    and silently fell back to pandas dayfirst=True, which reads '1988-04-11' as
    day=04 month=11 and returns 1988-11-04: wrong, no error. A guess that cannot
    be wrong does not exist, so the caller must have decided the order already —
    from unambiguous rows in the same column, or from a human answer.

    Measured on the current dataset: 30,279 dob rows have day > 12 and 0 have
    month > 12, so the file is day-first. 19,721 rows (39.4%) have both <= 12 and
    are only resolvable from the column, never from the value itself.
    """
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None

    parts = NUMERIC_DATE.match(text)
    if parts:
        first, second, third = parts.group(1), parts.group(3), parts.group(4)
        if len(first) == 4:
            # Year-first is ISO 8601 by convention: the second field is the month.
            # A documented convention, not a locale guess.
            year, month, day = first, second, third
        else:
            year = third
            a, b = int(first), int(second)
            if a > 12:
                month, day = b, a
            elif b > 12:
                month, day = a, b
            else:
                # Ambiguous on its own; only the recorded answer resolves it.
                month, day = (b, a) if dayfirst else (a, b)
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return None

    # A named month states the month, so these need no day/month decision.
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def detect_date_order(values: pd.Series) -> tuple[str | None, dict]:
    """Infer day-first vs month-first from the rows that are not ambiguous.

    Returns (order, evidence) where order is None when the column cannot be
    resolved: both orders are present, or no row is unambiguous at all. Both
    cases need a human answer and must not be guessed.
    """
    parts = values.dropna().astype(str).str.extract(NUMERIC_DATE.pattern)
    # Groups: 1=first field, 2=separator, 3=second field, 4=third field.
    first = pd.to_numeric(parts[0], errors="coerce")
    second = pd.to_numeric(parts[2], errors="coerce")
    # A 4-digit first field is year-first, which the ISO convention already fixes.
    day_gt_12 = int((first[first < 1000] > 12).sum())
    month_gt_12 = int((second[first < 1000] > 12).sum())
    ambiguous = int(
        (
            (first < 1000)
            & (first <= 12)
            & (second <= 12)
            & first.notna()
            & second.notna()
        ).sum()
    )

    if day_gt_12 and not month_gt_12:
        order = "dmy"
    elif month_gt_12 and not day_gt_12:
        order = "mdy"
    else:
        order = None

    evidence = {
        "year_first_rows": int((first >= 1000).sum()),
        "day_gt_12": day_gt_12,
        "month_gt_12": month_gt_12,
        "ambiguous_rows": ambiguous,
        "detected_order": order,
    }
    return order, evidence


def resolve_dayfirst(values: pd.Series, column: str, explicit: str | None) -> tuple[bool, dict]:
    """Decide the day/month order for one column, or refuse to guess."""
    detected, evidence = detect_date_order(values)
    order = explicit or detected
    evidence["source"] = "explicit" if explicit else ("detected" if detected else "unresolved")
    evidence["applied_order"] = order

    if order is None:
        raise SystemExit(
            f"Cannot tell whether {column!r} is d/m/Y or m/d/Y.\n"
            f"  day > 12 in {evidence['day_gt_12']:,} rows, month > 12 in "
            f"{evidence['month_gt_12']:,} rows, both <= 12 (ambiguous) in "
            f"{evidence['ambiguous_rows']:,} rows.\n"
            "  Every date comparison and the dob_exact/city_dob blocking rules "
            "depend on this answer, so it is not guessed.\n"
            "  Re-run with --date-order dmy or --date-order mdy, or set DATE_ORDER "
            "in src/config.py."
        )
    return order == "dmy", evidence


def normalize_device_ids(value):
    if pd.isna(value):
        return None
    parts = re.split(r"[;,|]", str(value))
    cleaned = []
    for part in parts:
        item = re.sub(r"\s+", "", part.strip().lower())
        if item:
            cleaned.append(item)
    return cleaned or None


def add_record_id(
    df: pd.DataFrame, start_index: int = 0
) -> pd.DataFrame:
    df = df.copy()
    if SOURCE_RECORD_ID_COLUMN and SOURCE_RECORD_ID_COLUMN in df.columns and df[SOURCE_RECORD_ID_COLUMN].is_unique:
        df.insert(0, "record_id", df[SOURCE_RECORD_ID_COLUMN].astype(str).map(lambda x: f"src_{x}"))
        return df

    df.insert(
        0,
        "record_id",
        [
            f"rec_{i:06d}"
            for i in range(start_index + 1, start_index + len(df) + 1)
        ],
    )
    return df


def add_blocking_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Derive coarse blocking keys from the standardized fields.

    Exact blocking on standardized identity values yields almost no candidates
    on this dataset (3,487 of 49,995,000 pairs on a 10k sample) because typos
    survive normalization. These keys are deliberately lossy prefixes so
    near-identical records land in the same block. They generate candidates
    only; similarity is still scored afterwards by Splink.
    """
    for column, length in (("first_name_std", 3), ("last_name_std", 3)):
        if column in df:
            df[f"{column}_pre{length}"] = df[column].str.slice(0, length)

    if "email_std" in df:
        local = df["email_std"].str.split("@", n=1).str[0]
        domain = df["email_std"].str.split("@", n=1).str[-1]
        df["email_local_pre3"] = local.str.slice(0, 3)
        df["email_domain_pre4"] = domain.str.slice(0, 4)

    if "phone_std" in df:
        # Country/area-code prefix; keeps the block strict enough to stay small.
        df["phone_pre7"] = df["phone_std"].str.slice(0, 7)

    if "dob_std" in df:
        df["dob_year_std"] = df["dob_std"].str.slice(0, 4)

    return df


def assert_blocking_columns(df: pd.DataFrame) -> list[str]:
    """Refuse to standardize a dataset that blocking cannot run on.

    `standardize()` skips a source column that is absent, so a batch missing `dob`
    simply produces no `dob_std`. Nothing complains until Splink raises MISSING
    COLUMN — after the new data has already been written and registered. Failing
    here names the missing source columns instead.
    """
    required = {col for _, cols in BENCHMARK_RULES for col in cols}
    missing = sorted(required - set(df.columns))
    if not missing:
        return []
    source_of = {}
    for canonical, source in COLUMN_MAP.items():
        source_of[f"{canonical}_std"] = source
    sources = sorted({source_of.get(m, m) for m in missing})
    raise SystemExit(
        f"This input cannot be blocked: {len(missing)} derived column(s) are absent.\n"
        f"  missing derived : {missing}\n"
        f"  missing source  : {sources}\n"
        "  The batch would be standardized but never linked. Add the columns, or "
        "remove the blocking rules that need them in BENCHMARK_RULES (src/config.py)."
    )


def standardize(
    df: pd.DataFrame,
    date_order: str | None = None,
    evidence: dict | None = None,
    start_index: int = 0,
) -> pd.DataFrame:
    df = add_record_id(df, start_index=start_index)
    text_fields = ["first_name", "last_name", "address", "city", "state", "country"]
    for canonical in text_fields:
        source = COLUMN_MAP[canonical]
        if source in df:
            df[f"{canonical}_std"] = df[source].map(normalize_name)

    source = COLUMN_MAP["email"]
    if source in df:
        df["email_std"] = df[source].map(normalize_email)

    source = COLUMN_MAP["phone"]
    if source in df:
        df["phone_std"] = df[source].map(normalize_phone)

    # Each date column resolves its own day/month order. They can differ between
    # columns and between batches, so a single global setting is not enough.
    date_evidence: dict[str, dict] = {}
    for canonical in ("dob", "signup_date"):
        source = COLUMN_MAP[canonical]
        if source not in df:
            continue
        dayfirst, ev = resolve_dayfirst(df[source], source, date_order)
        ev["day_first"] = dayfirst
        date_evidence[canonical] = ev
        df[f"{canonical}_std"] = df[source].map(lambda v: normalize_date(v, dayfirst))

    source = COLUMN_MAP["device_ids"]
    if source in df:
        df["device_ids_std"] = df[source].map(normalize_device_ids)

    out = add_blocking_keys(df)
    if evidence is not None:
        evidence.update(date_evidence)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Standardize CRM records into derived _std columns.")
    parser.add_argument(
        "--date-order",
        choices=["auto", "dmy", "mdy"],
        default="auto",
        help=(
            "Day/month order for ambiguous dates (both parts <= 12). 'auto' derives it from "
            "rows where day > 12 or month > 12 and refuses to guess when the column gives no "
            f"evidence. Overrides DATE_ORDER in src/config.py ({DATE_ORDER or 'unset'})."
        ),
    )
    parser.add_argument(
        "--input",
        nargs="+",
        default=None,
        metavar="CSV",
        help=(
            "Raw CSV(s) to read in the given order instead of RAW_DATA_PATH. The output is "
            "rebuilt from exactly these files, so listing a single new batch REPLACES the "
            "parquet instead of appending to it. Tahap 3 registry makes this safe automatically."
        ),
    )
    parser.add_argument(
        "--register",
        metavar="CSV",
        default=None,
        help=(
            "Register this data/raw file as a new batch, then rebuild from every "
            "registered batch. The start_index is derived from the registry, so a "
            "new batch cannot collide with the record_ids already stored."
        ),
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help=(
            "Override the first record_id index. Only meaningful WITHOUT the batch "
            "registry; with a registry the index is derived and this must stay 0."
        ),
    )
    args = parser.parse_args()
    if args.start_index < 0:
        raise SystemExit("--start-index must be >= 0")
    explicit = None if args.date_order == "auto" else args.date_order
    explicit = explicit or DATE_ORDER

    from . import registry

    if args.register:
        new_path = Path(args.register)
        if not new_path.exists():
            raise SystemExit(f"{new_path} not found")
        batch = registry.register(new_path, len(load_raw(new_path)))
        print(
            f"Registered batch {batch['batch_id']}: {batch['file']} "
            f"{batch['rows']:,} rows -> {batch['record_id_range'][0]}..{batch['record_id_range'][1]}"
        )

    registered = registry.registered_paths()
    if args.input:
        source_files = [Path(p) for p in args.input]
    elif registered:
        if args.start_index:
            raise SystemExit(
                "--start-index cannot be combined with the batch registry: the registry "
                "owns the numbering. Drop the flag."
            )
        source_files = registry.source_paths()
        print(f"Reading {len(source_files)} registered batch(es) from the registry")
    else:
        source_files = registry.source_paths()

    previous_rows = 0
    if PROCESSED_DATA_PATH.exists():
        try:
            previous_rows = len(pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id"]))
        except Exception:
            previous_rows = 0

    missing = [str(p) for p in source_files if not p.exists()]
    if missing:
        raise SystemExit(f"Input file(s) not found: {missing}")
    df = (
        pd.concat([load_raw(p) for p in source_files], ignore_index=True)
        if len(source_files) > 1
        else load_raw(source_files[0])
    )

    evidence: dict = {}
    out = standardize(df, explicit, evidence, start_index=args.start_index)
    missing = assert_blocking_columns(out)
    PROCESSED_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(PROCESSED_DATA_PATH, index=False)

    for canonical, ev in evidence.items():
        print(
            f"{canonical}: day>12 in {ev['day_gt_12']:,} rows, month>12 in {ev['month_gt_12']:,} "
            f"rows, ambiguous in {ev['ambiguous_rows']:,} -> applied {ev['applied_order']} "
            f"({ev['source']})"
        )

    # Provenance: the date answer is a decision, not a detail. Without it a later
    # reader cannot tell whether a date column was parsed or guessed.
    write_meta(
        PROCESSED_DATA_PATH,
        artifact="standardized_records",
        rows=len(out),
        source_files=[p.name for p in source_files],
        start_index=args.start_index,
        date_evidence=evidence,
    )
    print(f"Saved: {PROCESSED_DATA_PATH}")
    print(f"Rows: {len(out):,}")
    print(f"record_id range: {out['record_id'].iloc[0]} .. {out['record_id'].iloc[-1]}")
    if previous_rows and len(out) < previous_rows:
        # The documented trap: a new batch read as --input silently shrinks the
        # dataset because the parquet is rebuilt, not appended to.
        print(
            f"WARNING: output has {len(out):,} rows but the previous parquet had "
            f"{previous_rows:,}. The new input REPLACED the stored data instead of adding "
            "to it. List every batch: --input a.csv b.csv."
        )
    print("Derived columns:")
    print([c for c in out.columns if c not in COLUMN_MAP.values()])


if __name__ == "__main__":
    main()
