from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from .config import COLUMN_MAP, OUTPUT_DIR, RAW_DATA_PATH


def load_raw(path: Path = RAW_DATA_PATH) -> pd.DataFrame:
    """Read a raw CSV whose delimiter and encoding are not guaranteed.

    The validator accepts ',' as well as ';' — a client export is just as
    likely to be comma separated. Reading a comma file with the old hardcoded
    `sep=";"` folded the whole header into ONE column, so the batch validated
    as ACCEPTED and then died in standardize, after registration. One
    definition of the reading rule lives in validate_upload.read_csv_any, so
    the validator and the pipeline cannot disagree about what a file contains.
    """
    from .validate_upload import read_csv_any

    if not path.exists():
        raise FileNotFoundError(
            f"Dataset tidak ditemukan: {path}\n"
            "Taruh CSV di data/raw/ atau ubah RAW_DATA_PATH di src/config.py."
        )
    frame, _info = read_csv_any(path)
    return frame


def load_dataset() -> pd.DataFrame:
    """Every file the batch registry currently names, concatenated.

    Profiling must read the same rows standardize will link. When profiling read
    the monolith while the registry pointed at two batches, the profile silently
    described a different dataset than the one being deduplicated.
    """
    from . import registry

    paths = registry.source_paths()
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"Registered batch file(s) missing: {missing}\n"
            "Re-register them, or fix data/processed/batch_registry.json."
        )
    frames = [load_raw(p) for p in paths]
    return frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)


def dataset_files() -> list[Path]:
    from . import registry

    return registry.source_paths()


def validate_columns(df: pd.DataFrame) -> dict:
    available = set(df.columns)
    mapping = {}
    missing = []
    for canonical, source in COLUMN_MAP.items():
        mapping[canonical] = source
        if source not in available:
            missing.append(source)
    return {"available": sorted(available), "missing_configured": missing, "mapping": mapping}


def profile_column(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        nulls = int(s.isna().sum())
        non_null = s.dropna().astype(str)
        rows.append(
            {
                "column": col,
                "dtype": str(s.dtype),
                "rows": n,
                "null_count": nulls,
                "null_pct": round(nulls / n * 100, 4) if n else 0.0,
                "unique_count": int(s.nunique(dropna=True)),
                "unique_pct": round(s.nunique(dropna=True) / n * 100, 4) if n else 0.0,
                "blank_string_count": int((non_null.str.strip() == "").sum()),
            }
        )
    return pd.DataFrame(rows)


def top_values(df: pd.DataFrame, column: str, n: int = 15) -> pd.DataFrame:
    if column not in df.columns:
        return pd.DataFrame(columns=[column, "count"])
    return df[column].value_counts(dropna=False).head(n).rename_axis(column).reset_index(name="count")


def name_anomalies(df: pd.DataFrame, column: str) -> dict:
    if column not in df.columns:
        return {"missing_column": True}
    s = df[column].fillna("").astype(str)
    return {
        "mixed_case_or_upper_count": int((s != s.str.lower()).sum()),
        "digit_count": int(s.str.contains(r"\d", regex=True, na=False).sum()),
        "symbol_count": int(s.str.contains(r"[^A-Za-z\s'’-]", regex=True, na=False).sum()),
        "repeated_character_count": int(s.str.count(r"(.)\1").gt(0).sum()),
    }


def phone_anomalies(df: pd.DataFrame, column: str) -> dict:
    if column not in df.columns:
        return {"missing_column": True}
    s = df[column].fillna("").astype(str)
    normalized_len = s.str.replace(r"\D", "", regex=True).str.len()
    return {
        "contains_letters": int(s.str.contains(r"[A-Za-z]", regex=True, na=False).sum()),
        "contains_punctuation": int(s.str.contains(r"[^0-9+()\-\s]", regex=True, na=False).sum()),
        "length_distribution": normalized_len.value_counts().sort_index().head(20).to_dict(),
    }


def duplicate_id_report(df: pd.DataFrame, customer_id: str) -> dict:
    if customer_id not in df.columns:
        return {"missing_column": True}
    s = df[customer_id]
    dup = s.value_counts(dropna=False)
    dup = dup[dup > 1]
    sizes = dup.value_counts().sort_index().to_dict()
    return {
        "unique_customer_id": int(s.nunique(dropna=True)),
        "duplicated_id_values": int((dup > 1).sum()),
        "rows_in_duplicated_id_groups": int(dup.sum()),
        "group_size_distribution": {str(k): int(v) for k, v in sizes.items()},
    }


def identifier_coverage(df: pd.DataFrame) -> dict:
    """Quantify how far the exact-equi-join blocking rules can possibly reach.

    Every rule in BENCHMARK_RULES is an exact match on a standardized field, so a
    record missing those fields cannot be linked to anything by construction.
    Without this number, "no candidates found" is indistinguishable from "no
    duplicates exist", and recall claims stay unfounded.
    """
    def null_count(canonical: str) -> int:
        source = COLUMN_MAP[canonical]
        return int(df[source].isna().sum()) if source in df.columns else -1

    email, phone, dob = null_count("email"), null_count("phone"), null_count("dob")
    both_missing = int(
        (
            df[COLUMN_MAP["email"]].isna()
            & df[COLUMN_MAP["phone"]].isna()
        ).sum()
    )
    # The two strongest rules are email_exact and phone_exact. A record missing
    # both can never be produced as a candidate by any current rule.
    return {
        "records": len(df),
        "missing_email": email,
        "missing_phone": phone,
        "missing_dob": dob,
        "missing_both_email_and_phone": both_missing,
        "pct_unlinkable_by_current_rules": round(both_missing / len(df) * 100, 4)
        if len(df)
        else 0.0,
        "note": (
            "Exact-equi-join rules cannot link a record whose email AND phone are "
            "both absent. This is a recall ceiling, not a duplicate count."
        ),
    }


def build_profile(df: pd.DataFrame) -> dict:
    customer_id = COLUMN_MAP["customer_id"]
    return {
        "shape": {"rows": len(df), "columns": len(df.columns)},
        "columns": list(df.columns),
        "column_profile": profile_column(df).to_dict(orient="records"),
        "duplicate_rows": int(df.duplicated().sum()),
        "duplicate_customer_id": duplicate_id_report(df, customer_id),
        "name_anomalies_first": name_anomalies(df, COLUMN_MAP["first_name"]),
        "name_anomalies_last": name_anomalies(df, COLUMN_MAP["last_name"]),
        "phone_anomalies": phone_anomalies(df, COLUMN_MAP["phone"]),
        "identifier_coverage": identifier_coverage(df),
        "top_values": {
            # data-profiling skill step 7: names, phone, email, address, device IDs.
            canonical: top_values(df, source).to_dict(orient="records")
            for canonical, source in COLUMN_MAP.items()
            if canonical in ("first_name", "last_name", "email", "phone", "address", "device_ids")
        },
    }


def main() -> None:
    start = time.perf_counter()
    df = load_dataset()
    validation = validate_columns(df)
    sources = dataset_files()
    print("Input: " + ", ".join(p.name for p in sources))
    print(f"Shape : {df.shape}")
    if validation["missing_configured"]:
        print("WARNING — configured columns not found:")
        for col in validation["missing_configured"]:
            print(f"  - {col}")
        print("Edit COLUMN_MAP di src/config.py sebelum lanjut.")

    summary = build_profile(df)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "profiling_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(summary["column_profile"]).to_csv(OUTPUT_DIR / "profiling_report.csv", index=False)

    print(f"Exact duplicate rows: {summary['duplicate_rows']}")
    print("Customer ID report:", summary["duplicate_customer_id"])
    coverage = summary["identifier_coverage"]
    print(
        f"Identifier coverage: missing email={coverage['missing_email']:,} "
        f"phone={coverage['missing_phone']:,} "
        f"both={coverage['missing_both_email_and_phone']:,} "
        f"({coverage['pct_unlinkable_by_current_rules']:.2f}% recall ceiling)"
    )
    print(f"Runtime: {time.perf_counter() - start:.2f}s")


if __name__ == "__main__":
    main()
