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

# Tiga kolom numerik dengan SATU pemisah berulang. Pola sengaja dibuat ketat:
# pola longgar dapat membuat '1988-04-11' terbaca sebagai 4 November.
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
    r"""Ambil angka saja dan buang ekstensi.

    PENGUKURAN pada berkas pengembangan 50 ribu baris sebelum perubahan ini:
    29.966 dari 50.000 nilai memiliki ekstensi "xNNN", dan `re.sub(r"\D", "")`
    memasukkan ekstensi ke dalam kunci. '(449) 977-1729' dan
    '449.977.1729x282' adalah nomor yang sama dari dua sistem, tetapi
    sebelumnya menghasilkan kunci berbeda sehingga tidak dapat dicocokkan.

    Yang dibuang hanya ekstensi, bukan seluruh nomor: nomor pusat yang sama
    dengan ekstensi berbeda tetap menjadi bukti organisasi yang sama, dan nomor
    utama adalah bagian yang dikenali customer sebagai nomor teleponnya.

    Docstring mentah digunakan dengan sengaja: docstring biasa mengubah "\D"
    di atas menjadi SyntaxWarning setiap kali modul diimpor.
    """
    if pd.isna(value):
        return None
    text = re.split(r"[xX]\s*\d+", str(value))[0]
    digits = re.sub(r"\D", "", text)
    return digits or None


def normalize_date(value, dayfirst: bool) -> str | None:
    """Ubah satu tanggal ke format ISO dengan menentukan urutan hari/bulan secara eksplisit.

    dayfirst WAJIB diberikan. Implementasi sebelumnya mencoba %d/%m/%Y lalu
    diam-diam beralih ke pandas dayfirst=True, yang membaca '1988-04-11' sebagai
    day=04 month=11 dan menghasilkan 1988-11-04: salah, tanpa pesan kesalahan.
    Tidak ada tebakan yang dijamin benar, sehingga pemanggil harus menentukan
    urutan terlebih dahulu — dari baris yang tidak ambigu pada kolom yang sama
    atau dari jawaban manusia.

    Pengukuran pada dataset saat ini: 30.279 baris dob memiliki hari > 12 dan
    tidak ada yang memiliki bulan > 12, sehingga format berkas adalah hari-bulan.
    Sebanyak 19.721 baris (39,4%) memiliki hari dan bulan <= 12, sehingga
    urutannya hanya dapat ditentukan dari keseluruhan kolom, bukan dari nilainya
    sendiri.
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
            # Menurut konvensi ISO 8601, jika tahun berada di awal, kolom kedua
            # adalah bulan. Ini konvensi terdokumentasi, bukan tebakan lokal.
            year, month, day = first, second, third
        else:
            year = third
            a, b = int(first), int(second)
            if a > 12:
                month, day = b, a
            elif b > 12:
                month, day = a, b
            else:
                # Nilai ini ambigu jika berdiri sendiri; hanya jawaban yang
                # tercatat yang dapat menentukannya.
                month, day = (b, a) if dayfirst else (a, b)
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return None

    # Nama bulan sudah menyatakan bulannya, jadi urutan hari/bulan tidak perlu
    # ditentukan untuk nilai-nilai ini.
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def detect_date_order(values: pd.Series) -> tuple[str | None, dict]:
    """Simpulkan urutan hari-bulan atau bulan-hari dari baris yang tidak ambigu.

    Kembalikan (order, evidence). Nilai order adalah None jika urutan kolom tidak
    dapat ditentukan: kedua urutan ditemukan atau tidak ada baris yang tidak
    ambigu. Kedua kondisi memerlukan jawaban manusia dan tidak boleh ditebak.
    """
    parts = values.dropna().astype(str).str.extract(NUMERIC_DATE.pattern)
    # Kelompok: 1=kolom pertama, 2=pemisah, 3=kolom kedua, 4=kolom ketiga.
    first = pd.to_numeric(parts[0], errors="coerce")
    second = pd.to_numeric(parts[2], errors="coerce")
    # Kolom pertama dengan 4 digit menunjukkan tahun di awal, sesuai konvensi ISO.
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
        # Every parsed row is year-first (ISO). d/m vs m/d is irrelevant —
        # normalize_date already handles YYYY-MM-DD. Without this the DB path
        # (where DuckDB returns DATE columns that db_source normalizes to ISO)
        # always raised "Cannot tell whether dob is d/m/Y or m/d/Y".
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
    """Turunkan kunci blocking umum dari kolom yang telah distandardisasi.

    Blocking persis pada nilai identitas terstandardisasi menghasilkan sangat
    sedikit kandidat di dataset ini (3.487 dari 49.995.000 pasangan pada sampel
    10 ribu baris) karena salah ketik tetap ada setelah normalisasi. Kunci ini
    sengaja menggunakan prefiks yang tidak utuh agar catatan yang hampir sama
    masuk ke blok yang sama. Kunci hanya menghasilkan kandidat; kemiripan tetap
    dinilai oleh Splink setelahnya.
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
        # Prefiks negara/kode area; menjaga blok tetap cukup ketat dan kecil.
        df["phone_pre7"] = df["phone_std"].str.slice(0, 7)

    if "dob_std" in df:
        df["dob_year_std"] = df["dob_std"].str.slice(0, 4)

    return df


def assert_blocking_columns(df: pd.DataFrame) -> list[str]:
    """Tolak standardisasi dataset yang tidak dapat diproses oleh blocking.

    `standardize()` melewati kolom sumber yang tidak tersedia, sehingga batch
    tanpa `dob` tidak menghasilkan `dob_std`. Tidak ada kesalahan sampai Splink
    melaporkan MISSING COLUMN, setelah data baru terlanjur ditulis dan
    didaftarkan. Pemeriksaan di sini menyebutkan kolom sumber yang hilang.
    """
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
            df[f"{canonical}_std"] = df[source].map(normalize_name)

    source = COLUMN_MAP["email"]
    if source in df:
        df["email_std"] = df[source].map(normalize_email)

    source = COLUMN_MAP["phone"]
    if source in df:
        df["phone_std"] = df[source].map(normalize_phone)

    # Setiap kolom tanggal menentukan urutan hari/bulannya sendiri. Urutannya
    # dapat berbeda antar kolom dan antar batch, sehingga satu pengaturan global
    # tidak cukup.
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
        # Berkas 50 ribu baris memakai `device_id(s)`, sedangkan batch_0005
        # memakai `device_id`. COLUMN_MAP hanya menampung satu nama per kolom
        # kanonis. Tanpa penanganan ini, 200 catatan batch_0005 tidak memiliki
        # acuan device dan 35 sisi MATCH-nya tidak dapat diverifikasi.
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

    # Asal-usul data: jawaban urutan tanggal merupakan keputusan, bukan detail.
    # Tanpanya, pembaca berikutnya tidak dapat mengetahui apakah tanggal diparse
    # atau hanya ditebak.
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
