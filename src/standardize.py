from __future__ import annotations

import argparse
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import (
    COLUMN_MAP,
    DATE_ORDER,
    DEVICE_ID_ALIASES,
    PROCESSED_DATA_PATH,
    RAW_DATA_PATH,
    SOURCE_RECORD_ID_COLUMN,
    write_meta,
    atomic_write_parquet,
    atomic_write_json,
    load_benchmark_rules,
)
from .profiling import load_raw

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

_LEET_TABLE = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "@": "a", "$": "s", "!": "i",
})

_PERSON_NAME_FIELDS = {"first_name", "last_name"}


def normalize_person_name(value) -> str | None:
    if pd.isna(value):
        return None
    return normalize_text(str(value).translate(_LEET_TABLE))


def normalize_email(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().lower()
    return text or None


def normalize_phone(value) -> str | None:
    r"""Ambil angka saja, buang ekstensi, dan seragamkan prefix internasional.

    Data asli memuat nomor yang sama dengan prefix berbeda (001..., 00..., 1...,
    0...). Tanpa normalisasi prefix, pasangan yang sama persis gagal cocok dan
    menjadi false negative. Aturan: buang '00' internasional, lalu buang satu
    '0' domestik di depan, sisanya angka Nasional.
    """
    if pd.isna(value):
        return None
    text = re.split(r"[xX]\s*\d+", str(value))[0]
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits or None


def normalize_date(value, dayfirst: bool) -> str | None:

    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None

    parts = NUMERIC_DATE.match(text)
    if parts:
        first, second, third = parts.group(1), parts.group(3), parts.group(4)
        if len(first) == 4:
            
            year, month, day = first, second, third
        else:
            year = third
            a, b = int(first), int(second)
            if a > 12:
                month, day = b, a
            elif b > 12:
                month, day = a, b
            else:

                month, day = (b, a) if dayfirst else (a, b)
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return None

    for fmt in ("%d-%b-%Y", "%d %b %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def detect_date_order(values: pd.Series) -> tuple[str | None, dict]:

    parts = values.dropna().astype(str).str.extract(NUMERIC_DATE.pattern)
    first = pd.to_numeric(parts[0], errors="coerce")
    second = pd.to_numeric(parts[2], errors="coerce")
    year_first = int((first >= 1000).sum())
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
    elif year_first > 0 and day_gt_12 == 0 and month_gt_12 == 0:
        order = "iso"
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
    """Tentukan urutan hari/bulan untuk satu kolom, atau tolak menebak."""
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
    for column, length in (("first_name_std", 3), ("last_name_std", 3)):
        if column in df:
            df[f"{column}_pre{length}"] = df[column].str.slice(0, length)

    if "email_std" in df:
        local = df["email_std"].str.split("@", n=1).str[0]
        domain = df["email_std"].str.split("@", n=1).str[-1]
        df["email_local_pre3"] = local.str.slice(0, 3)
        df["email_domain_pre4"] = domain.str.slice(0, 4)

    if "phone_std" in df:
        # Prefiks negara/kode area; menjaga blok tetap cukup ketat dan kecil.
        df["phone_pre7"] = df["phone_std"].str.slice(0, 7)
        # Dipakai rule name_fuzzy_last4; wajib ada agar model bisa diprediksi.
        df["phone_last4"] = df["phone_std"].str.slice(-4)

    if "dob_std" in df:
        df["dob_year_std"] = df["dob_std"].str.slice(0, 4)

    if "last_name_std" in df:
        # Soundex grouping catch typo variants ("Smith" / "Smyth").
        df["phonetic_last_name"] = df["last_name_std"].map(soundex)

    if "first_name_std" in df:
        df["phonetic_first_name"] = df["first_name_std"].map(soundex)

    return df


def soundex(name: str | None) -> str | None:
    if not name or pd.isna(name):
        return None
    name = re.sub(r"[^A-Za-z]", "", str(name)).upper()
    if not name:
        return None
    first = name[0]
    mapping = str.maketrans("BFPVCGJKQSXZDTLMNR", "111122222222334556")
    core = name[1:].translate(mapping)
    core = re.sub(r"[^0-9]", "", core)
    result = first
    prev = ""
    for ch in core:
        if ch != prev:
            result += ch
        prev = ch
    result = f"{result[:4]:<04.4}"
    return result


def assert_blocking_columns(df: pd.DataFrame) -> list[str]:
    required = {col for _, cols in load_benchmark_rules() for col in cols}
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
        "remove the blocking rules that need them in the blocking config."
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
            # Fold leet hanya untuk nama. Alamat berisi angka ("no. 3") dan
            # akan rusak bila 3->e diterapkan di sana.
            mapper = (
                normalize_person_name
                if canonical in _PERSON_NAME_FIELDS
                else normalize_name
            )
            df[f"{canonical}_std"] = df[source].map(mapper)

    source = COLUMN_MAP["email"]
    if source in df:
        df["email_std"] = df[source].map(normalize_email)

    source = COLUMN_MAP["phone"]
    if source in df:
        df["phone_std"] = df[source].map(normalize_phone)
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
    if source not in df and DEVICE_ID_ALIASES:
        source = next((alt for alt in DEVICE_ID_ALIASES if alt in df), source)
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
    atomic_write_parquet(out, PROCESSED_DATA_PATH)

    for canonical, ev in evidence.items():
        print(
            f"{canonical}: day>12 in {ev['day_gt_12']:,} rows, month>12 in {ev['month_gt_12']:,} "
            f"rows, ambiguous in {ev['ambiguous_rows']:,} -> applied {ev['applied_order']} "
            f"({ev['source']})"
        )

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
        # Jebakan yang diketahui: membaca batch baru sebagai --input diam-diam
        # mengecilkan dataset karena parquet dibangun ulang, bukan ditambahi.
        print(
            f"WARNING: output has {len(out):,} rows but the previous parquet had "
            f"{previous_rows:,}. The new input REPLACED the stored data instead of adding "
            "to it. List every batch: --input a.csv b.csv."
        )
    print("Derived columns:")
    print([c for c in out.columns if c not in COLUMN_MAP.values()])


if __name__ == "__main__":
    main()
