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
import io
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import COLUMN_MAP, OUTPUT_DIR, load_benchmark_rules

REPORT_PATH = OUTPUT_DIR / "upload_validation_report.json"

REQUIRED_COLUMNS = ["first_name", "last_name"]
ONE_OF = [("email", "phone")]

# Bentuk email, bukan kebersihannya. Hanya menolak yang TIDAK mungkin menjadi
# alamat: tanpa '@', tanpa domain, atau '@' ganda. 'a@b.c' diterima — TLD satu
# karakter memang sah, dan menolaknya akan menandai data yang benar sebagai rusak.
# Terverifikasi 2026-10-16: nolak 'budi@', '@gmail.com', 'budi', 'budi@@gmail.com',
# 'budi gmail.com'; terima 48.960 alamat pada CSV 50k.
EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Label kegagalan per kolom: pesan blocking harus menyebut gejala yang benar,
# bukan satu bentuk umum yang dipakai untuk semua tipe data. Bentuknya kata
# kerja supaya bisa disisipkan setelah "does not" dan setelah "every row".
_SHAPE_FAILURE = {
    "email": "parse as a valid email address",
    "phone": "yield any digits (a usable phone)",
    "dob": "parse as a date",
}


def shape_report(df: pd.DataFrame, date_evidence: dict | None = None) -> dict:
    """Ukur apakah kolom identitas berisi tipe nilai yang benar.

    PEMISAHAN INTI: nilai kosong BUKAN kegagalan bentuk. Email kosong adalah
    data hilang (recall turun, terlihat di null_profile); email 'budi@' adalah
    data salah bentuk (nilai yang sama di dua baris menembus aturan email_exact).
    Keduanya perlu dilaporkan terpisah — jika digabung, kolom yang salah
    dipetakan tampak sama saja dengan kolom yang banyak kosong, dan salah
    peta justru yang paling berbahaya karena tidak menghasilkan error.

    Tanpa ambang persentase: baseline terukur 2026-10-16 pada CSV 50k dan
    Postgres 2.003 = 100% lolos untuk ketiga kolom (0 non-blank gagal), sehingga
    angka seperti "tolak di bawah 90%" tidak punya dasar pengukuran.
    """
    from .standardize import normalize_date, normalize_phone

    date_evidence = date_evidence or {}
    n = len(df)
    out: dict[str, dict] = {}

    # email: bentuk, sebelum normalize_email yang hanya menurunkan huruf.
    # phone: hasil normalize_phone yang kosong = baris itu tak menghasilkan
    #   nomor sama sekali. '021-abc' menjadi '021' sehingga TIDAK dihitung gagal
    #   di sini; ekstensi 'x282' sah dan dibuang oleh normalize_phone.
    checks = (
        ("email", lambda v: bool(EMAIL_SHAPE.match(v.strip().lower()))),
        ("phone", lambda v: bool(normalize_phone(v))),
    )
    for canonical, is_shaped in checks:
        source = COLUMN_MAP[canonical]
        if source not in df.columns:
            continue
        raw = df[source].fillna("").astype(str)
        present = raw[raw.str.strip() != ""]
        shaped = present.map(is_shaped)
        bad = present[~shaped]
        out[canonical] = {
            "column": source,
            "rows": n,
            "non_blank": int(len(present)),
            "blank": int(n - len(present)),
            "shaped": int(shaped.sum()) if len(present) else 0,
            "unshaped": int(len(bad)),
            "unshaped_pct": round(100.0 * len(bad) / len(present), 3) if len(present) else 0.0,
            "samples": bad.head(5).tolist(),
        }

    source = COLUMN_MAP["dob"]
    if source in df.columns:
        raw = df[source].fillna("").astype(str)
        present = raw[raw.str.strip() != ""]
        order = (date_evidence.get("dob") or {}).get("applied_order")
        if order is None:
            # Urutan hari/bulan belum terjawab, sehingga ukur pun tidak sah.
            # Laporan bentuk tidak boleh menandai kolom gagal hanya karena
            # pertanyaan tanggal belum dijawab.
            out["dob"] = {
                "column": source,
                "rows": n,
                "non_blank": int(len(present)),
                "blank": int(n - len(present)),
                "measurable": False,
                "reason": "date order unresolved — re-run with --date-order dmy|mdy",
            }
        else:
            dayfirst = order == "dmy"
            shaped = present.map(lambda v: normalize_date(v, dayfirst) is not None)
            bad = present[~shaped]
            out["dob"] = {
                "column": source,
                "rows": n,
                "non_blank": int(len(present)),
                "blank": int(n - len(present)),
                "shaped": int(shaped.sum()) if len(present) else 0,
                "unshaped": int(len(bad)),
                "unshaped_pct": round(100.0 * len(bad) / len(present), 3) if len(present) else 0.0,
                "measurable": True,
                "applied_order": order,
                "samples": bad.head(5).tolist(),
            }

    # customer_pk bukan kolom identitas, tetapi kunci update-in-place. Nilai
    # kembar membuat pemetaan customer_pk -> record_id diam-diam membuang satu
    # pihak, sehingga pembaruan berikutnya menimpa record yang salah.
    if "customer_pk" in df.columns:
        pk = df["customer_pk"]
        total = int(pk.notna().sum())
        unique = int(pk.nunique())
        out["customer_pk"] = {
            "column": "customer_pk",
            "rows": n,
            "non_blank": total,
            "blank": int(n - total),
            "unique": unique,
            "duplicated": total - unique,
            "unique_ok": total == 0 or total == unique,
        }
    return out


def shape_findings(shape: dict) -> tuple[list[str], list[str]]:
    """Terjemahkan laporan bentuk jadi alasan blocking + peringatan.

    Blocking HANYA untuk bukti kategorikal yang tidak butuh ambang: tidak ada
    satu pun nilai non-kosong yang lolos, sehingga kolom itu memang bukan tipe
    yang diharapkan — gejala salah peta, bukan data kotor. Sisanya peringatan.
    """
    blocking: list[str] = []
    warnings: list[str] = []
    for canonical, info in shape.items():
        if canonical == "customer_pk":
            if not info["unique_ok"]:
                blocking.append(
                    f"column 'customer_pk' has {info['duplicated']:,} duplicated value(s) "
                    f"across {info['non_blank']:,} rows — update-in-place maps "
                    "customer_pk -> record_id and would silently keep only one, then "
                    "overwrite the other record on the next refresh"
                )
            continue
        if info.get("measurable") is False:
            warnings.append(f"shape of '{info['column']}' not checked: {info['reason']}")
            continue
        label = _SHAPE_FAILURE.get(canonical, canonical)
        if not info["non_blank"]:
            continue  # kolom kosong sudah ditangani null_profile
        if info["unshaped"] == info["non_blank"]:
            blocking.append(
                f"column '{info['column']}' does not {label} in ANY of its "
                f"{info['non_blank']:,} non-blank value(s) (e.g. {info['samples'][:3]!r}) "
                f"— every row failed the {canonical} shape test, which is a mapping "
                "or type problem, not dirty data"
            )
        elif info["unshaped"]:
            warnings.append(
                f"{info['unshaped']:,} of {info['non_blank']:,} non-blank values in "
                f"'{info['column']}' do not {label} ({info['unshaped_pct']:.2f}%), "
                f"e.g. {info['samples'][:3]!r} — those rows lose this field as linkage evidence"
            )
    return blocking, warnings


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

# Ambang kemiripan nama kolom. 0.7 dipilih karena cukup mengenali variasi
# umum ("first_nm" -> "first_name", "telp" -> "phone_number") tanpa sampai
# memetakan kolom yang salah secara diam-diam (mis. "city" -> "state" punya
# kemiripan rendah dan akan tetap diabaikan). Nilai ini hanya membentuk saran
# peta di laporan — batch tidak pernah direname otomatis.
COLUMN_SIMILARITY_THRESHOLD = 0.7


def normalized_levenshtein_similarity(a: str, b: str) -> float:
    """Kemiripan 1.0 - levenshtein_distance/max(len), di kisaran [0, 1].

    Implementasi hitung-tangan dua baris agar proyek tidak bergantung paket baru
    untuk satu fungsi; dataset kolom biasanya jauh lebih kecil dari data dalamnya.
    """
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(
                prev[j] + 1,          # hapus
                cur[j - 1] + 1,       # sisipkan
                prev[j - 1] + (ca != cb),  # substitusi
            )
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


def suggest_column_mappings(df_columns: list[str], threshold: float = COLUMN_SIMILARITY_THRESHOLD) -> list[dict]:
    """Sarankan pemetaan kolom sumber yang mirip nama kanonis tapi belum cocok persis.

    Ini hanya diagnosis: kolom sumber tetap apa adanya sampai pengguna/pemetingan
    eksternal (DB_COLUMN_MAP atau UI) menegaskan persamaannya. Batch tidak
    ditolak karena saran ini.
    """
    canonical_targets = [(canonical, source) for canonical, source in COLUMN_MAP.items()]

    available = set(df_columns)
    exact = {s for _, s in canonical_targets} & available
    suggestions: list[dict] = []

    for canonical, expected in canonical_targets:
        # sudah cocok persis -> tidak usah sarankan
        if expected in available:
            continue
        for col in df_columns:
            if col in exact:
                continue
            score = normalized_levenshtein_similarity(col, expected)
            if score >= threshold:
                suggestions.append(
                    {
                        "canonical": canonical,
                        "expected_source": expected,
                        "found_column": col,
                        "similarity": round(score, 3),
                    }
                )
    # skor tertinggi dulu supaya UI menampilkan kandidat terbaik lebih dahulu
    suggestions.sort(key=lambda s: s["similarity"], reverse=True)
    return suggestions


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

    date_ev = date_format_evidence(df)
    shape = shape_report(df, date_ev)
    shape_blocking, shape_warnings = shape_findings(shape)
    blocking.extend(shape_blocking)
    warnings.extend(shape_warnings)

    return {
        "status": "rejected" if blocking else "accepted",
        "rows": len(df),
        "columns": len(df.columns),
        "available_columns": sorted(available),
        "blocking": blocking,
        "warnings": warnings,
        "null_profile": null_report,
        "shape": shape,
        "column_suggestions": suggest_column_mappings(sorted(available)),
        "exact_duplicate_rows": int(df.duplicated(subset=scalar_columns).sum())
        if len(df) and scalar_columns
        else 0,
        "duplicate_check_columns": len(scalar_columns),
        "date_formats": date_ev,
    }


def _has_list_values(series: pd.Series, sample: int = 50) -> bool:
    """Bernilai True jika beberapa nilai pertama berupa list/array, bukan skalar."""
    for value in series.head(sample):
        if isinstance(value, (list, tuple, set, np.ndarray)):
            return True
    return False


def validate_payload(payload: bytes, name: str = "upload.csv") -> dict:
    """Validate a CSV given as in-memory bytes (no temp file on disk).

    Returns the same report shape as validate(), with a "file" metadata block.
    """
    # Reuse the encoding-detection logic from read_csv_any.
    text = None
    encoding_used = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = payload.decode(encoding)
            encoding_used = encoding
            break
        except (UnicodeDecodeError, AttributeError):
            continue
    if text is None:
        raise SystemExit(f"{name}: could not decode as utf-8 or latin-1")

    first_line = text.split("\n", 1)[0]
    best = max(DELIMITERS, key=lambda d: first_line.count(d))
    if first_line.count(best) == 0:
        frame = pd.read_csv(io.BytesIO(payload), sep=None, engine="python", low_memory=False)
        return validate(frame) | {
            "file": {
                "name": name,
                "delimiter": "sniffed",
                "encoding": encoding_used,
                "note": "no delimiter found in the header; pandas sniffed the file",
            }
        }
    frame = pd.read_csv(io.BytesIO(payload), sep=best, low_memory=False)
    return validate(frame) | {
        "file": {"name": name, "delimiter": DELIMITERS[best], "encoding": encoding_used}
    }


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

    shape = report.get("shape", {})
    if shape:
        print("\nShape / type checks (blank is missing data, not a shape failure):")
        for canonical, info in shape.items():
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

    print(f"\nSaved: {args.report}")
    raise SystemExit(1 if report["blocking"] else 0)


if __name__ == "__main__":
    main()
