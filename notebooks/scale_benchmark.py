from __future__ import annotations

import argparse
import gc
import json
import random
import shutil
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import psutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import registry
from src.config import (
    ENTITY_MAP_PATH,
    MASTER_PATH,
    PROCESSED_DATA_PATH,
    meta_path,
    predictions_path,
    write_meta,
)
from src.incremental import HISTORY_PATH, apply, compute
from src.labels import QUEUE_PATH
from src.standardize import standardize

BATCH_FILE = "scale_batch.csv"
BATCH_ROWS = 100
BATCH_CLONES = 10

CONSONANTS = "bcdfghjklmnpqrstvwxyz"
VOWELS = "aeiou"
STREETS = [f"Jl.{i:03d} Kenanga" for i in range(500)]
CITIES = [
    ("Jakarta", "DKI"), ("Bandung", "Jabar"), ("Surabaya", "Jatim"),
    ("Medan", "Sumut"), ("Makassar", "Sulsel"), ("Yogyakarta", "DIY"),
    ("Palembang", "Sumbar"), ("Denpasar", "Bali"), ("Pontianak", "Kalbar"),
    ("Manado", "Sulteng"),
]
DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me"]
SOURCES = ["branch_form", "call_center", "mobile_app", "partner_api"]
# Skema mentah yang digunakan bersama oleh berkas 50 ribu baris dan setiap batch terdaftar.
RAW_COLUMNS = [
    "customer_id", "first_name", "last_name", "email", "phone_number",
    "gender", "dob", "signup_date", "address", "city", "state", "country",
    "device_id(s)", "source",
]

ARTIFACTS = [
    PROCESSED_DATA_PATH,
    ENTITY_MAP_PATH,
    MASTER_PATH,
    predictions_path(full=True),
    QUEUE_PATH,
    HISTORY_PATH,
    registry.REGISTRY_PATH,
]


def name_pool(rng: random.Random, count: int, syllables: int) -> list[str]:
    pool: set[str] = set()
    while len(pool) < count:
        name = "".join(
            rng.choice(CONSONANTS) + rng.choice(VOWELS) for _ in range(syllables)
        )
        pool.add(name.capitalize())
    return sorted(pool)


def generate_old(n: int, rng: random.Random) -> pd.DataFrame:
    first_pool = name_pool(rng, 100, 2)
    last_pool = name_pool(rng, 200, 3)
    first = rng.choices(first_pool, k=n)
    last = rng.choices(last_pool, k=n)
    area = rng.choices(range(1000), k=n)
    street = rng.choices(STREETS, k=n)
    city_idx = rng.choices(range(len(CITIES)), k=n)
    frame = pd.DataFrame(
        {
            "customer_id": [f"CUS{i:07d}" for i in range(n)],
            "first_name": first,
            "last_name": last,
            "email": [
                f"{f.lower()}.{l.lower()}{i:07d}@{rng.choice(DOMAINS)}"
                for i, (f, l) in enumerate(zip(first, last))
            ],
            "phone_number": [f"+62 8{a:03d} {i:07d}" for i, a in enumerate(area)],
            "gender": rng.choices(["M", "F", "X"], k=n),
            "dob": [
                f"{rng.randrange(1, 29):02d}/{rng.randrange(1, 13):02d}/{rng.randrange(1948, 2007)}"
                for _ in range(n)
            ],
            "signup_date": [
                f"{rng.randrange(1, 28):02d}/{rng.randrange(1, 13):02d}/{rng.randrange(2016, 2026)}"
                for _ in range(n)
            ],
            "address": [f"{rng.randrange(1, 900)} {s}" for s in street],
            "city": [CITIES[c][0] for c in city_idx],
            "state": [CITIES[c][1] for c in city_idx],
            "country": ["Indonesia"] * n,
            "device_id(s)": [f"dev_{i:07d}" for i in range(n)],
            "source": rng.choices(SOURCES, k=n),
        }
    )
    # 2% duplikat persis: orang yang sama dicatat dua kali dengan customer_id baru.
    dup_idx = rng.sample(range(n), k=max(1, n // 50))
    clones = frame.iloc[dup_idx].copy()
    clones["customer_id"] = [f"CUS{i:07d}" for i in range(n, n + len(clones))]
    return pd.concat([frame, clones], ignore_index=True)


def generate_batch(old_std: pd.DataFrame, rng: random.Random) -> pd.DataFrame:
    n_new = BATCH_ROWS - BATCH_CLONES
    first = rng.choices(old_std["first_name"].tolist(), k=n_new)
    last = rng.choices(old_std["last_name"].tolist(), k=n_new)
    area = rng.choices(range(1000), k=n_new)
    street = rng.choices(STREETS, k=n_new)
    city_idx = rng.choices(range(len(CITIES)), k=n_new)
    start = len(old_std)
    fresh = pd.DataFrame(
        {
            "customer_id": [f"CUS{i:07d}" for i in range(start, start + n_new)],
            "first_name": first,
            "last_name": last,
            "email": [
                f"{f.lower()}.{l.lower()}{i:07d}@{rng.choice(DOMAINS)}"
                for i, (f, l) in enumerate(zip(first, last))
            ],
            "phone_number": [f"+62 8{a:03d} {i:07d}" for i, a in enumerate(area)],
            "gender": rng.choices(["M", "F", "X"], k=n_new),
            "dob": [
                f"{rng.randrange(1, 29):02d}/{rng.randrange(1, 13):02d}/{rng.randrange(1948, 2007)}"
                for _ in range(n_new)
            ],
            "signup_date": [
                f"{rng.randrange(1, 28):02d}/{rng.randrange(1, 13):02d}/{rng.randrange(2016, 2026)}"
                for _ in range(n_new)
            ],
            "address": [f"{rng.randrange(1, 900)} {s}" for s in street],
            "city": [CITIES[c][0] for c in city_idx],
            "state": [CITIES[c][1] for c in city_idx],
            "country": ["Indonesia"] * n_new,
            "device_id(s)": [f"dev_b{i:07d}" for i in range(n_new)],
            "source": rng.choices(SOURCES, k=n_new),
        }
    )

    clone_src = old_std[RAW_COLUMNS].sample(
        n=BATCH_CLONES, random_state=rng.randrange(10**9)
    )
    clones = clone_src.copy()
    clones["customer_id"] = [
        f"CUS{i:07d}" for i in range(start + n_new, start + BATCH_ROWS)
    ]
    return pd.concat([fresh, clones], ignore_index=True)


def setup_old_data(n: int, rng: random.Random) -> int:
    raw = generate_old(n, rng)
    evidence: dict = {}
    std = standardize(raw, "dmy", evidence, start_index=0)
    del raw
    gc.collect()
    std.to_parquet(PROCESSED_DATA_PATH, index=False)
    write_meta(
        PROCESSED_DATA_PATH,
        artifact="standardized_records",
        rows=len(std),
        source_files=["scale_old_synthetic"],
        incremental_batch=None,
    )
    emap = pd.DataFrame(
        {
            "record_id": std["record_id"],
            
            "entity_id": "ent_"
            + pd.Series(range(1, len(std) + 1), dtype="object").astype(str).str.zfill(6),
        }
    )
    emap.to_parquet(ENTITY_MAP_PATH, index=False)
    write_meta(
        ENTITY_MAP_PATH,
        artifact="entity_map",
        scope="full",
        records=len(emap),
        entities=len(emap),
        incremental_batch=None,
    )
    return len(std)


def setup_registry(batch_path: Path, start_index: int) -> dict:
    batch = {
        "batch_id": 1,
        "file": BATCH_FILE,
        "rows": BATCH_ROWS,
        "start_index": start_index,
        "end_index": start_index + BATCH_ROWS - 1,
        "record_id_range": [
            f"rec_{start_index + 1:06d}",
            f"rec_{start_index + BATCH_ROWS:06d}",
        ],
        "sha256": registry.sha256_of(batch_path),
        "registered_at": datetime.now().isoformat(timespec="seconds"),
    }
    registry.save(
        {
            "version": registry.REGISTRY_VERSION,
            "next_start_index": start_index + BATCH_ROWS,
            "batches": [batch],
        }
    )
    return batch


def measure(fn) -> dict:
    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    peak = [rss0]
    stop = threading.Event()

    def sample() -> None:
        while not stop.wait(0.1):
            peak[0] = max(peak[0], proc.memory_info().rss)

    thread = threading.Thread(target=sample)
    thread.start()
    buf = StringIO()
    started = time.perf_counter()
    try:
        with redirect_stdout(buf):
            result = fn()
    finally:
        elapsed = time.perf_counter() - started
        stop.set()
        thread.join()
    return {
        "seconds": round(elapsed, 2),
        "peak_rss_gb": round((peak[0] - rss0) / 1e9, 3),
        "stdout": buf.getvalue(),
        "result": result,
    }


def backup(scratch: Path) -> dict[Path, bool]:
    existed: dict[Path, bool] = {}
    for path in ARTIFACTS:
        for target in (path, meta_path(path)):
            if target.exists():
                shutil.copy2(target, scratch / target.name)
        existed[path] = path.exists()
    return existed


def restore(scratch: Path, existed: dict[Path, bool]) -> None:
    for path, was_there in existed.items():
        for target in (path, meta_path(path)):
            if was_there:
                backup_file = scratch / target.name
                if backup_file.exists():
                    shutil.copy2(backup_file, target)
                elif target.exists():
                    target.unlink(missing_ok=True)
            elif target.exists():
                target.unlink(missing_ok=True)


def run_size(size: int) -> dict:
    rng = random.Random(20261009 + size)
    scratch = Path(tempfile.mkdtemp(prefix="scale_bench_"))
    batch_path = PROJECT_ROOT / "data" / "raw" / BATCH_FILE
    existed: dict[Path, bool] = {}
    result: dict = {"size": size}
    available = psutil.virtual_memory().available / 1e9
    result["ram_available_gb"] = round(available, 1)
    try:
        existed = backup(scratch)
        t_setup = time.perf_counter()
        old_rows = setup_old_data(size, rng)
        old_std = pd.read_parquet(PROCESSED_DATA_PATH)
        raw_batch = generate_batch(old_std, rng)
        del old_std
        gc.collect()
        raw_batch.to_csv(batch_path, sep=";", index=False, encoding="utf-8")
        batch = setup_registry(batch_path, old_rows)
        result["old_rows"] = old_rows
        result["setup_seconds"] = round(time.perf_counter() - t_setup, 1)
        result["parquet_mb"] = round(PROCESSED_DATA_PATH.stat().st_size / 1e6, 1)

        comp = measure(lambda: compute(batch, None))
        state = comp["result"]
        preds = state["new_preds"]
        result["compute_seconds"] = comp["seconds"]
        result["compute_peak_rss_gb"] = comp["peak_rss_gb"]
        result["compute_stdout"] = comp["stdout"]
        result["scored_pairs"] = len(preds)
        result["match_edges"] = int((preds["decision"] == "MATCH").sum())
        result["review_pairs"] = int((preds["decision"] == "REVIEW").sum())

        app = measure(lambda: apply(state))
        result["apply_seconds"] = app["seconds"]
        result["apply_peak_rss_gb"] = app["peak_rss_gb"]
        result["apply_stdout"] = app["stdout"]
    finally:
        restore(scratch, existed)
        shutil.rmtree(scratch, ignore_errors=True)
        batch_path.unlink(missing_ok=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, required=True, help="unique old rows")
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "scale_benchmark.jsonl",
        help="append results as one JSON line",
    )
    args = parser.parse_args()

    result = run_size(args.size)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, default=str) + "\n")
    print(
        f"size={result['size']} old_rows={result['old_rows']:,} "
        f"setup={result['setup_seconds']}s parquet={result['parquet_mb']}MB "
        f"compute={result['compute_seconds']}s/{result['compute_peak_rss_gb']}GB "
        f"apply={result['apply_seconds']}s/{result['apply_peak_rss_gb']}GB "
        f"pairs={result['scored_pairs']} match={result['match_edges']} "
        f"review={result['review_pairs']} ram={result['ram_available_gb']}GB"
    )


if __name__ == "__main__":
    main()
