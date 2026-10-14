"""Validasi batch yang diunggah sebelum didaftarkan.

Tahap ini menolak batch lebih awal jika strukturnya tidak sesuai untuk pipeline
linkage. Tujuannya adalah mencegah berkas ditulis dan didaftarkan jika Splink
nantinya akan gagal karena kolom yang diperlukan tidak tersedia.

Aturan:
- Wajib: first_name, last_name, dan setidaknya salah satu dari email/phone.
- Wajib: setiap kolom sumber yang digunakan aturan blocking aktif di
  BENCHMARK_RULES. Daftar ini diturunkan dari config, bukan ditulis tetap,
  sehingga validator dan standardize() selalu selaras.
- Membantu: kolom yang meningkatkan recall tetapi tidak digunakan untuk blocking.
- Opsional: kolom lain yang tercantum di COLUMN_MAP.

Nama kolom harus diambil hanya dari COLUMN_MAP. Menebak nama sumber di sini
dapat menyembunyikan kesalahan pengetikan pipeline dan menyebabkan batch
diterima secara keliru.

Laporan juga menyertakan metadata operasional, bukan hanya kesalahan validasi:
- pemisah dan pengodean yang benar-benar digunakan pada berkas unggahan;
- bukti urutan tanggal agar UI dapat menampilkan urutan yang terdeteksi sebagai
  pilihan awal saat menanyakan format dd/mm atau mm/dd.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import COLUMN_MAP, OUTPUT_DIR, load_benchmark_rules

REPORT_PATH = OUTPUT_DIR / "upload_validation_report.json"

REQUIRED_COLUMNS = ["first_name", "last_name"]
ONE_OF = [("email", "phone")]


def blocking_source_columns(config_path: str | Path | None = None) -> set[str]:
    """Kolom sumber yang bentuk _std-nya digunakan oleh aturan blocking aktif.

    Diturunkan dari BENCHMARK_RULES agar validator dan src.standardize selalu
    sepakat mengenai kolom yang harus tersedia di dalam batch.
    """
    rules = load_benchmark_rules(config_path)
    keys = {col for _, cols in rules for col in cols}
    derived = {k[:-4] for k in keys if k.endswith("_std")}
    derived |= {k.split("_std_")[0] for k in keys if "_std_" in k}
    return {COLUMN_MAP[c] for c in COLUMN_MAP if c in derived}


def optional_source_columns() -> set[str]:
    return set(COLUMN_MAP.values()) - blocking_source_columns() - {
        COLUMN_MAP[c] for c in REQUIRED_COLUMNS
    } - {COLUMN_MAP[c] for c, _ in ONE_OF}

DELIMITERS = {";": ";", ",": ",", "\t": "\t", "|": "|"}


def read_csv_any(path: Path) -> tuple[pd.DataFrame, dict]:
    """Baca CSV yang pemisah dan pengodeannya belum diketahui.

    load_raw() mengasumsikan pemisah ';'. Berkas ekspor klien bisa saja memakai
    koma, dan penggunaan pemisah yang keliru akan diam-diam menggabungkan semua
    kolom menjadi satu judul.
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

    best = max(DELIMITERS, key=lambda d: first_line.count(d))
    if first_line.count(best) == 0:
        # biarkan pandas mendeteksi pemisah.
        frame = pd.read_csv(path, sep=None, engine="python", low_memory=False)
        return frame, {
            "delimiter": "sniffed",
            "encoding": encoding_used,
            "note": "no delimiter found in the header; pandas sniffed the file",
        }

    frame = pd.read_csv(path, sep=best, low_memory=False)
    return frame, {"delimiter": DELIMITERS[best], "encoding": encoding_used}


def date_format_evidence(df: pd.DataFrame) -> dict:
    """Bukti urutan hari/bulan untuk tiap kolom tanggal menggunakan parser standardisasi."""
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
    """Kembalikan laporan. `blocking` memuat alasan batch harus ditolak."""
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

    needed = blocking_source_columns()
    missing_keys = sorted(needed - available)
    if missing_keys:
        blocking.append(
            "column(s) required by the active blocking rules are absent: "
            + ", ".join(missing_keys)
            + " — the batch would standardize but never link. Add them, or drop the "
            "rules that need them in the blocking config (src/config.py)."
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
    """Bernilai True jika beberapa nilai pertama berupa list/array, bukan skalar."""
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
