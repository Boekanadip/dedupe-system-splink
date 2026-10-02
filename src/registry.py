"""Which raw files make up the current dataset, and which record_ids they own.

The failure this prevents
`standardize --input new_batch.csv` rebuilt the parquet from that file ALONE, so
record_ids restarted at rec_000001 and collided with rows already stored. The
warning printed after the fact ("output has N rows but the previous parquet had
M") was real, but the damage was already done.

The registry makes the index arithmetic impossible to get wrong: a batch is
registered once, and `next_start_index` is derived from what is already there.
Re-registering the same file is refused by content hash, not by filename, because
the same data under a different name is the more likely mistake.

Durability, stated plainly
`record_id` is positional within a batch. Editing a registered file changes the
ids of everything after it in that file. The sha256 is stored so that change is
detectable rather than silent — it is not prevented.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "batch_registry.json"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

REGISTRY_VERSION = 1


def _empty() -> dict:
    return {"version": REGISTRY_VERSION, "next_start_index": 0, "batches": []}


def load() -> dict:
    if not REGISTRY_PATH.exists():
        return _empty()
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    data.setdefault("next_start_index", sum(b["rows"] for b in data.get("batches", [])))
    return data


def save(registry: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    registry["updated_at"] = datetime.now().isoformat(timespec="seconds")
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def registered_paths() -> list[Path]:
    return [RAW_DIR / b["file"] for b in load()["batches"]]


def source_paths() -> list[Path]:
    """The files that make up the dataset right now.

    Single definition so profiling and standardize cannot read different data.
    Before a registry exists this is the configured RAW_DATA_PATH, which keeps
    the pre-registry behaviour working.
    """
    from .config import RAW_DATA_PATH

    paths = registered_paths()
    return paths if paths else [RAW_DATA_PATH]


def next_start_index() -> int:
    """Where the next batch's records begin. Derived, never supplied by a user."""
    return int(load()["next_start_index"])


def register(path: Path, rows: int) -> dict:
    """Add a batch, refusing anything that would double-count or overlap."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")

    registry = load()
    digest = sha256_of(path)

    for batch in registry["batches"]:
        if batch["sha256"] == digest:
            raise SystemExit(
                f"{path.name} is already registered as batch {batch['batch_id']} "
                f"(sha256 {digest[:12]}...). Registering it again would duplicate "
                f"{batch['rows']:,} records and collide on record_id."
            )
        if batch["file"] == path.name:
            raise SystemExit(
                f"{path.name} is already registered as batch {batch['batch_id']} with a "
                f"different content hash. The file changed after registration, which "
                f"would shift every record_id after it. Re-register deliberately and "
                f"accept the renumbering, or restore the original file."
            )

    start = int(registry["next_start_index"])
    batch = {
        "batch_id": max((b["batch_id"] for b in registry["batches"]), default=0) + 1,
        "file": path.name,
        "rows": rows,
        "start_index": start,
        "end_index": start + rows - 1,
        "record_id_range": [f"rec_{start + 1:06d}", f"rec_{start + rows:06d}"],
        "sha256": digest,
        "registered_at": datetime.now().isoformat(timespec="seconds"),
    }
    registry["batches"].append(batch)
    registry["next_start_index"] = start + rows
    save(registry)
    return batch


def seed(names: list[str]) -> dict:
    """Register an initial set of batches in order, from scratch.

    Row counts are read from the files, not passed in: a wrong count here would
    hand the next batch a start_index in the middle of an existing one.
    """
    save(_empty())
    for name in names:
        path = RAW_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"{path} not found")
        rows = _row_count(path)
        register(path, rows)
    return load()


def _row_count(path: Path) -> int:
    import pandas as pd

    from .profiling import load_raw

    return len(load_raw(path))


def verify_against(standardized_path: Path) -> dict:
    """Do the registered record_ids actually cover the standardized parquet?"""
    registry = load()
    if not registry["batches"]:
        return {"status": "unavailable", "reason": "no batches registered"}
    if not standardized_path.exists():
        return {"status": "unavailable", "reason": f"{standardized_path.name} not found"}

    import pandas as pd

    ids = set(pd.read_parquet(standardized_path, columns=["record_id"])["record_id"])
    covered = 0
    for batch in registry["batches"]:
        covered += batch["rows"]
    expected = sum(batch["rows"] for batch in registry["batches"])

    return {
        "status": "measured",
        "batches": len(registry["batches"]),
        "registered_rows": expected,
        "standardized_rows": len(ids),
        "counts_match": expected == len(ids),
        "ranges": {b["file"]: b["record_id_range"] for b in registry["batches"]},
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Show or seed the batch registry.")
    parser.add_argument(
        "--seed",
        nargs="+",
        metavar="CSV",
        help=(
            "Register these data/raw files as the dataset, in order, starting from an "
            "empty registry. Row counts are read from the files."
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.seed:
        registry = seed(args.seed)
        print(f"Registered {len(registry['batches'])} batch(es).")
        for b in registry["batches"]:
            print(
                f"  {b['batch_id']}  {b['file']:38s} {b['rows']:>8,d} rows  "
                f"{b['record_id_range'][0]}..{b['record_id_range'][1]}"
            )
        print(f"  next_start_index: {registry['next_start_index']:,}")
        return

    registry = load()
    if args.json:
        print(json.dumps(registry, indent=2))
        return

    batches = registry["batches"]
    if not batches:
        print(f"No batches registered. Registry: {REGISTRY_PATH}")
        print("Seed it with: python -m src.registry --seed batch_0001.csv batch_0002.csv")
        return

    print(f"Registry: {REGISTRY_PATH}")
    print(f"next_start_index: {registry['next_start_index']:,}")
    print()
    header = f"{'id':>3} {'file':38s} {'rows':>8s} {'start':>7s} {'end':>7s}  record_id range"
    print(header)
    print("-" * len(header))
    for b in batches:
        present = "" if (RAW_DIR / b["file"]).exists() else "  [FILE MISSING]"
        print(
            f"{b['batch_id']:>3} {b['file']:38s} {b['rows']:>8,d} {b['start_index']:>7,d} "
            f"{b['end_index']:>7,d}  {b['record_id_range'][0]}..{b['record_id_range'][1]}{present}"
        )
    print()
    print(f"total rows: {sum(b['rows'] for b in batches):,}")


if __name__ == "__main__":
    main()
