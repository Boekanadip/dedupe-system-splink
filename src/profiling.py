from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from .config import COLUMN_MAP, DEVICE_ID_ALIASES, OUTPUT_DIR, RAW_DATA_PATH


def load_raw(path: Path = RAW_DATA_PATH) -> pd.DataFrame:
    from .validate_upload import read_csv_any

    if not path.exists():
        raise FileNotFoundError(
            f"Dataset tidak ditemukan: {path}\n"
            "Taruh CSV di data/raw/ atau ubah RAW_DATA_PATH di src/config.py."
        )
    frame, _info = read_csv_any(path)
    return frame


def load_dataset() -> pd.DataFrame:
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


def _resolve_source(df: pd.DataFrame, canonical: str) -> str | None:
    source = COLUMN_MAP.get(canonical)
    if source and source in df.columns:
        return source
    aliases = {
        "phone": ["phone", "phone_number"],
        "device_ids": list(DEVICE_ID_ALIASES) if 'DEVICE_ID_ALIASES' in globals() else ["device_id"],
    }
    for alt in aliases.get(canonical, []):
        if alt in df.columns:
            return alt
    return source


def identifier_coverage(df: pd.DataFrame) -> dict:
    def null_count(canonical: str) -> int:
        source = _resolve_source(df, canonical)
        return int(df[source].isna().sum()) if source and source in df.columns else -1

    email = null_count("email")
    phone = null_count("phone")
    dob = null_count("dob")
    email_src = _resolve_source(df, "email")
    phone_src = _resolve_source(df, "phone")
    if email_src in df.columns and phone_src in df.columns:
        both_missing = int((df[email_src].isna() & df[phone_src].isna()).sum())
    else:
        both_missing = -1
    return {
        "records": len(df),
        "missing_email": email,
        "missing_phone": phone,
        "missing_dob": dob,
        "missing_both_email_and_phone": both_missing,
        "pct_unlinkable_by_current_rules": round(both_missing / len(df) * 100, 4)
        if len(df) and both_missing >= 0
        else None,
        "note": (
            "Exact-equi-join rules cannot link a record whose email AND phone are "
            "both absent. This is a recall ceiling, not a duplicate count."
        ),
    }


def build_profile(df: pd.DataFrame) -> dict:
    customer_id = _resolve_source(df, "customer_id") or COLUMN_MAP["customer_id"]
    return {
        "shape": {"rows": len(df), "columns": len(df.columns)},
        "columns": list(df.columns),
        "column_profile": profile_column(df).to_dict(orient="records"),
        "duplicate_rows": int(df.duplicated().sum()),
        "duplicate_customer_id": duplicate_id_report(df, customer_id),
        "name_anomalies_first": name_anomalies(df, _resolve_source(df, "first_name") or COLUMN_MAP["first_name"]),
        "name_anomalies_last": name_anomalies(df, _resolve_source(df, "last_name") or COLUMN_MAP["last_name"]),
        "phone_anomalies": phone_anomalies(df, _resolve_source(df, "phone") or COLUMN_MAP["phone"]),
        "identifier_coverage": identifier_coverage(df),
        "top_values": {
            canonical: top_values(df, _resolve_source(df, canonical) or source).to_dict(orient="records")
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
