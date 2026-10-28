from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "crm_50000_customers_dirty_v3.csv"
PROCESSED_DATA_PATH = PROJECT_ROOT / "data" / "processed" / "crm_standardized.parquet"
LABELS_DIR = PROJECT_ROOT / "data" / "labels"

OUTPUT_DIR = PROJECT_ROOT / "outputs"

PREDICTIONS_SAMPLE_PATH = OUTPUT_DIR / "splink_predictions_sample.parquet"
PREDICTIONS_FULL_PATH = OUTPUT_DIR / "splink_predictions.parquet"
ENTITY_MAP_PATH = OUTPUT_DIR / "entity_map.parquet"
MASTER_PATH = OUTPUT_DIR / "master_customers.parquet"

SCOPE_SAMPLE = "sample"
SCOPE_FULL = "full"

PIPELINE_LOCK = OUTPUT_DIR / ".pipeline_running"


def predictions_path(full: bool) -> Path:
    return PREDICTIONS_FULL_PATH if full else PREDICTIONS_SAMPLE_PATH


def scope_of(full: bool) -> str:
    return SCOPE_FULL if full else SCOPE_SAMPLE


def meta_path(artifact: Path) -> Path:
    return artifact.with_suffix(artifact.suffix + ".meta.json")


def read_meta(path: Path) -> dict:
    """Baca berkas asal-usul artefak; hasil kosong jika berkas tidak ada."""
    meta_file = meta_path(path)
    if not meta_file.exists():
        return {}
    return json.loads(meta_file.read_text(encoding="utf-8"))


def write_meta(path: Path, **fields) -> None:
    """Tulis secara atomik melalui berkas sementara agar tidak terbaca sebagian."""
    path.parent.mkdir(parents=True, exist_ok=True)
    target = meta_path(path)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(fields, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, target)


STAGING_DIR = OUTPUT_DIR / ".staging"
STAGING_MANIFEST = STAGING_DIR / "manifest.json"
STAGING_ENV = "PIPELINE_STAGING"


def _staged_name(path: Path) -> str:
    """Nama unik berkas di .staging/: nama asli dan hash singkat folder induk,
    supaya outputs/entity_map.parquet dan data/processed/entity_map.parquet
    tidak bertabrakan (walau praktisnya tidak terjadi)."""
    import hashlib

    parent_hash = hashlib.md5(str(Path(path).parent).encode()).hexdigest()[:8]
    return f"{parent_hash}_{Path(path).name}"


def _read_manifest() -> dict:
    if not STAGING_MANIFEST.exists():
        return {}
    try:
        return json.loads(STAGING_MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_manifest(manifest: dict) -> None:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STAGING_MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, STAGING_MANIFEST)


def _register_staged(staged: Path, real: Path) -> None:
    manifest = _read_manifest()
    manifest[staged.name] = str(real)
    _write_manifest(manifest)


def active_path(path: Path) -> Path:
    """Tentukan jalur berkas yang harus dibaca.

    Proses turunan pipeline (PIPELINE_STAGING=1) membaca versi staging jika ada,
    agar langkah berikutnya membaca keluaran langkah sebelumnya, bukan data
    lama. Pembaca luar (Streamlit) tidak mengatur variabel lingkungan tersebut,
    sehingga selalu membaca berkas yang sudah di-commit.
    """
    if os.environ.get(STAGING_ENV) != "1":
        return Path(path)
    staged = STAGING_DIR / _staged_name(path)
    if staged.exists():
        return staged
    return Path(path)


def _stage_write(tmp: Path, path: Path) -> None:
    """Pindahkan berkas .tmp yang sudah jadi ke .staging/ dan catat di manifest."""
    path = Path(path)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staged = STAGING_DIR / _staged_name(path)
    os.replace(tmp, staged)
    _register_staged(staged, path)


def atomic_write_parquet(frame, path: Path, **kwargs) -> None:
    """Tulis DataFrame. Saat pipeline berjalan: ke .staging/. Di luar pipeline:
    tulis secara atomik ke jalur asli, misalnya dari halaman ambang tanpa run_all."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.to_parquet(tmp, index=False, **kwargs)
    if os.environ.get(STAGING_ENV) == "1":
        _stage_write(tmp, path)
    else:
        os.replace(tmp, path)


def atomic_write_text(text: str, path: Path, encoding: str = "utf-8") -> None:
    """Tulis teks ke staging saat pipeline berjalan, atau langsung jika tidak."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    if os.environ.get(STAGING_ENV) == "1":
        _stage_write(tmp, path)
    else:
        os.replace(tmp, path)


def atomic_write_json(obj, path: Path, indent: int = 2) -> None:
    """Tulis objek Python sebagai JSON."""
    atomic_write_text(json.dumps(obj, indent=indent, default=str), path)


def atomic_write_csv(frame, path: Path, **kwargs) -> None:
    """Tulis DataFrame sebagai CSV. JANGAN pakai atomic_write_parquet untuk berkas
    .csv — fungsi tersebut menulis format parquet ke berkas berekstensi .csv dan merusaknya
    (pernah terjadi pada 2026-10-12: silver_pairs.csv dan review_queue.csv
    jadi tidak terbaca)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.to_csv(tmp, index=False, **kwargs)
    if os.environ.get(STAGING_ENV) == "1":
        _stage_write(tmp, path)
    else:
        os.replace(tmp, path)


def append_jsonl(entry: dict, path: Path) -> None:
    """Tambahkan satu baris JSON ke berkas JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")


def finalize_staged() -> int:
    """Tukar semua berkas .staging/ ke jalur aslinya, lalu bersihkan.

    Ini titik "commit" proses. Sebelum dipanggil, pembaca luar melihat keadaan lama
    sepenuhnya; sesudahnya, state baru sepenuhnya. Jendela inkonsistensi tinggal
    mikrosekon (waktu os.replace per file), bukan 70-465 detik seperti dulu.

    Kembalikan jumlah berkas yang ditukar.
    """
    manifest = _read_manifest()
    swapped = 0
    for name, real in manifest.items():
        staged = STAGING_DIR / name
        if not staged.exists():
            continue
        dest = Path(real)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, dest)
        swapped += 1
    # Bersihkan sisa (termasuk .tmp yang tertinggal jika proses gagal).
    if STAGING_DIR.exists():
        for leftover in STAGING_DIR.iterdir():
            leftover.unlink(missing_ok=True)
    return swapped


def discard_staged() -> int:
    """Buang semua berkas .staging/ tanpa menyentuh jalur asli.

    Dipakai kalau run gagal: state lama tetap utuh, tidak ada yang ditukar.
    """
    manifest = _read_manifest()
    count = len(manifest)
    if STAGING_DIR.exists():
        for leftover in STAGING_DIR.iterdir():
            leftover.unlink(missing_ok=True)
    return count


def staged_pending() -> dict:
    """Manifest staging yang belum di-commit. Kosong jika tidak ada proses aktif."""
    return _read_manifest()


# --- Pipeline lock ---


def acquire_pipeline_lock(note: str = "") -> None:
    """Tandai pipeline sedang berjalan. Catat PID agar kunci basi dapat dideteksi
    (proses sudah berhenti tetapi kuncinya tertinggal)."""
    PIPELINE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    import time

    PIPELINE_LOCK.write_text(
        json.dumps({"pid": os.getpid(), "started_at": time.time(), "note": note}),
        encoding="utf-8",
    )


def release_pipeline_lock() -> None:
    PIPELINE_LOCK.unlink(missing_ok=True)


def pipeline_locked() -> dict | None:
    """Kembalikan informasi jika pipeline sedang berjalan, atau None jika tidak.

    Kunci yang lebih tua dari 2 jam dianggap basi (proses gagal tetapi kunci
    tertinggal) dan tidak memblokir.
    """
    import time

    if not PIPELINE_LOCK.exists():
        return None
    try:
        info = json.loads(PIPELINE_LOCK.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        PIPELINE_LOCK.unlink(missing_ok=True)
        return None
    age = time.time() - float(info.get("started_at", 0))
    if age > 7200:
        PIPELINE_LOCK.unlink(missing_ok=True)
        return None
    return info

COLUMN_MAP = {
    "customer_id": "customer_id",
    "client_id": "client_id",
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
    "phone": "phone_number",
    "gender": "gender",
    "dob": "dob",
    "signup_date": "signup_date",
    "address": "address",
    "city": "city",
    "state": "state",
    "country": "country",
    "device_ids": "device_id(s)",
    "source": "source",
}

DEVICE_ID_ALIASES: tuple[str, ...] = ("device_id",)
# Isi hanya kalau DB asli memakai nama berbeda. Contoh:
#     DB_COLUMN_MAP = {
#         "first_nm": "first_name",
#         "e_mail":   "email",
#         "telp":     "phone_number",
#         "tgl_lahir":"dob",
#     }
DB_COLUMN_MAP: dict[str, str] = {
    "cust_id": "source_id",
    "client_id": "client_id",
    "nama_depan": "first_name",
    "nama_belakang": "last_name",
    "e_mail": "email",
    "email_address": "email",
    "telp": "phone_number",
    "no_telp": "phone_number",
    "telepon": "phone_number",
    "alamat_lengkap": "address",
    "kota": "city",
    "provinsi": "state",
    "negara": "country",
    "tanggal_lahir": "dob",
    "tgl_lahir": "dob",
    "tanggal_daftar": "signup_date",
    "jenis_kelamin": "gender",
}

SOURCE_RECORD_ID_COLUMN = None

# sehingga berkas dapat menentukan urutan "dmy" sendiri.
DATE_ORDER: str | None = None  # "dmy" | "mdy"

RANDOM_SEED = 42
SMOKE_SAMPLE_SIZE = 10000

# Default blocking rules (fallback when no config file).
DEFAULT_BENCHMARK_RULES: list[tuple[str, list[str]]] = [
    ("email_exact", ["email_std"]),
    ("phone_exact", ["phone_std"]),
    ("name_exact", ["first_name_std", "last_name_std"]),
    ("city_dob", ["city_std", "dob_std"]),
    ("dob_exact", ["dob_std"]),
    ("address_city", ["address_std", "city_std"]),
    ("phone_prefix", ["phone_pre7"]),
    ("name_prefix", ["last_name_std_pre3", "first_name_std_pre3"]),
    ("name_prefix_state", ["last_name_std_pre3", "state_std"]),
    ("email_domain_name", ["email_domain_pre4", "last_name_std_pre3", "first_name_std_pre3"]),
    ("city_state_dob_year", ["city_std", "state_std", "dob_year_std"]),
    # Tambahan blocking rules baru untuk kurangi candidate pairs
    ("email_domain", ["email_domain_pre4"]),
    ("city_state_dob", ["city_std", "state_std", "dob_std"]),
    ("phone_last4", ["phone_std"]),  # 4 digit terakhir telepon
    # Blocking rules untuk fuzzy match
    ("email_domain_fuzzy", ["email_domain_pre4"]),
    ("city_state_dob_fuzzy", ["city_std", "state_std", "dob_std"]),
    ("name_fuzzy_last4", ["last_name_std_pre3", "phone_last4"]),
]

# Backward compat: BENCHMARK_RULES stays importable as the default list.
BENCHMARK_RULES = DEFAULT_BENCHMARK_RULES


def load_benchmark_rules(config_path: str | Path | None = None) -> list[tuple[str, list[str]]]:
    """Load blocking rules from a JSON file; fallback to DEFAULT_BENCHMARK_RULES.

    Config file format: [{"name": "...", "columns": ["col1", "col2"]}, ...]
    """
    from pathlib import Path
    import json

    path = Path(config_path) if config_path else PROJECT_ROOT / "config" / "blocking_rules.json"
    if not path.exists():
        return DEFAULT_BENCHMARK_RULES
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [(item["name"], item["columns"]) for item in data]
    except (json.JSONDecodeError, KeyError, TypeError, OSError):
        return DEFAULT_BENCHMARK_RULES

LAMBDA_RECALL_ASSUMPTION = 1.0

M_ELSE_LEVEL_FLOOR: float | None = 0.05

# Contact agreement is strong evidence of a true match; raise m-prob from 0.60 → 0.75
CONTACT_M_PROB: float = 0.75
M_ELSE_LEVEL_FLOOR_BY_FIELD: dict[str, float] = {
    "dob_std": 0.001,        # tanggal lahir beda -> hampir pasti orang berbeda
    "phone_std": 0.001,      # nomor telepon beda -> kuat menolak
    "email_std": 0.005,      # email beda -> cukup kuat (bisa ganti email)
    "first_name_std": 0.02,  # nama bisa salah ketik / ganti
    "last_name_std": 0.01,
    "address_std": 0.02,     # alamat bisa pindah
    "state_std": 0.02,       # state bisa pindah; log2(m/u)=50 → bukan penolak kuat
    # city/country sengaja TIDAK di-override: memang sering kosong/salah.
}


def m_else_floor_for(column: str) -> float | None:
    """Nilai batas bawah untuk satu kolom, dengan fallback ke M_ELSE_LEVEL_FLOOR."""
    if M_ELSE_LEVEL_FLOOR is None:
        return None
    return M_ELSE_LEVEL_FLOOR_BY_FIELD.get(column, M_ELSE_LEVEL_FLOOR)


MATCH_THRESHOLD = 0.82
REVIEW_THRESHOLD = 1e-8

_OVERRIDE = OUTPUT_DIR / "thresholds_override.json"
if _OVERRIDE.exists():
    try:
        _t = json.loads(_OVERRIDE.read_text(encoding="utf-8"))
        MATCH_THRESHOLD = float(_t.get("match_threshold", MATCH_THRESHOLD))
        REVIEW_THRESHOLD = float(_t.get("review_threshold", REVIEW_THRESHOLD))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass  # jika ditimpa, gunakan nilai bawaan
