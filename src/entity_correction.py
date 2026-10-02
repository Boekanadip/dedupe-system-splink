"""Manual entity membership correction: split / merge, with an audit trail.

Triage flags (membership_flags.csv) only REPORT a wrong merge; this module
ACTS on it. Every operation is append-only logged to
outputs/entity_history.jsonl so an entity's formation can be reconstructed.

Guards (mirrors the smoke-test invariants — a manual edit must not silently
break what the test suite asserts):
  * merge — refused when both entities carry different device ids (false-merge
    signal on this dataset) unless --force.
  * split — refused when it would separate a pair decided MATCH unless --force.

After a successful op, master rows of the touched entities are rebuilt with the
same function incremental.py uses, so lineage/conflicts stay consistent.

Run:
    python -m src.entity_correction --split ent_000123 rec_0001 rec_0002 --reason "salah gabung"
    python -m src.entity_correction --merge ent_000123 ent_000456 --reason "satu orang"
    python -m src.entity_correction --history            # print the audit log
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import (
    ENTITY_MAP_PATH,
    MASTER_PATH,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    predictions_path,
    read_meta,
    write_meta,
)

HISTORY_PATH = OUTPUT_DIR / "entity_history.jsonl"


def _append(record: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _device_map(records: pd.DataFrame) -> dict[str, frozenset]:
    ids = (
        records[["record_id", "device_ids_std"]]
        .explode("device_ids_std")
        .dropna(subset=["device_ids_std"])
    )
    return ids.groupby("record_id")["device_ids_std"].apply(frozenset).to_dict()


def _match_edges() -> pd.DataFrame:
    preds = predictions_path(full=True)
    if not preds.exists():
        return pd.DataFrame(columns=["record_id_l", "record_id_r"])
    frame = pd.read_parquet(preds, columns=["record_id_l", "record_id_r", "decision"])
    return frame[frame["decision"] == "MATCH"][["record_id_l", "record_id_r"]]


def _rebuild_master(entity_ids: set[str]) -> int:
    """Recompute master rows for touched entities (shared logic w/ incremental).

    Also drops master rows whose entity_id no longer exists in the entity map.
    A merge removes the source entity entirely; without this its master row
    would survive and the file would claim an entity that has no records.
    """
    from .incremental import recompute_master_rows

    records = pd.read_parquet(PROCESSED_DATA_PATH)
    entity_map = pd.read_parquet(ENTITY_MAP_PATH)
    frame = records.merge(entity_map, on="record_id", how="inner")
    recomputed = recompute_master_rows(frame, entity_ids)
    master = pd.read_parquet(MASTER_PATH)
    master = master[~master["entity_id"].isin(entity_ids)]
    master = master[master["entity_id"].isin(set(entity_map["entity_id"]))]
    if not recomputed.empty:
        master = pd.concat([master, recomputed], ignore_index=True)
    master.to_parquet(MASTER_PATH, index=False)
    meta = read_meta(MASTER_PATH)
    meta.update(entities=len(master), records=int(master["record_count"].sum()))
    write_meta(MASTER_PATH, **meta)
    return len(recomputed)


def split(entity_id: str, record_ids: list[str], reason: str, actor: str, force: bool) -> None:
    entity_map = pd.read_parquet(ENTITY_MAP_PATH)
    members = set(entity_map.loc[entity_map["entity_id"] == entity_id, "record_id"])
    unknown = set(record_ids) - members
    if unknown:
        raise SystemExit(f"record tidak ada di {entity_id}: {sorted(unknown)}")
    if not (members - set(record_ids)):
        raise SystemExit("Semua record dikeluarkan — entity jadi kosong. Tidak diizinkan.")

    edges = _match_edges()
    leaving = set(record_ids)
    crossing = edges[
        edges["record_id_l"].isin(leaving) ^ edges["record_id_r"].isin(leaving)
    ]
    crossing = crossing[
        crossing["record_id_l"].isin(members) & crossing["record_id_r"].isin(members)
    ]
    if len(crossing) and not force:
        raise SystemExit(
            f"Split memisahkan {len(crossing)} pasangan MATCH:\n"
            + crossing.head(10).to_string(index=False)
            + "\n  Itu melanggar invariant 'MATCH tidak pernah dipisah'. Ulangi dengan --force kalau memang benar."
        )

    next_id = int(entity_map["entity_id"].str.split("_").str[1].astype(int).max()) + 1
    new_entity = f"ent_{next_id:06d}"
    entity_map.loc[entity_map["record_id"].isin(leaving), "entity_id"] = new_entity
    entity_map.to_parquet(ENTITY_MAP_PATH, index=False)

    touched = _rebuild_master({entity_id, new_entity})
    meta = read_meta(ENTITY_MAP_PATH)
    meta["entities"] = int(entity_map["entity_id"].nunique())
    write_meta(ENTITY_MAP_PATH, **meta)

    _append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": "split",
            "from_entity": entity_id,
            "to_entity": new_entity,
            "records": sorted(leaving),
            "reason": reason,
            "actor": actor,
            "forced": force,
        }
    )
    print(f"Split {len(leaving)} record -> {new_entity} (dari {entity_id})")
    print(f"  master rows rebuilt: {touched}")
    print(f"  audit: {HISTORY_PATH.name}")


def merge(entity_a: str, entity_b: str, reason: str, actor: str, force: bool) -> None:
    if entity_a == entity_b:
        raise SystemExit("Dua entity sama.")
    entity_map = pd.read_parquet(ENTITY_MAP_PATH)
    known = set(entity_map["entity_id"])
    for e in (entity_a, entity_b):
        if e not in known:
            raise SystemExit(f"{e} tidak ada di entity_map.")

    target, source = sorted((entity_a, entity_b))  # lower id wins (aturan clustering)

    records = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id", "device_ids_std"])
    dev = _device_map(records)
    src_records = set(entity_map.loc[entity_map["entity_id"] == source, "record_id"])
    tgt_records = set(entity_map.loc[entity_map["entity_id"] == target, "record_id"])
    dev_src = set().union(*(dev.get(r, frozenset()) for r in src_records))
    dev_tgt = set().union(*(dev.get(r, frozenset()) for r in tgt_records))
    if dev_src and dev_tgt and dev_src != dev_tgt and not force:
        raise SystemExit(
            "Merge ditolak: kedua entity membawa device id BERBEDA (sinyal false merge "
            f"pada dataset ini).\n  {entity_a}: {sorted(dev_tgt)}\n  {entity_b}: {sorted(dev_src)}\n"
            "  Ulangi dengan --force kalau manusia memang memutuskan demikian."
        )

    entity_map.loc[entity_map["entity_id"] == source, "entity_id"] = target
    entity_map.to_parquet(ENTITY_MAP_PATH, index=False)

    touched = _rebuild_master({target})
    meta = read_meta(ENTITY_MAP_PATH)
    meta["entities"] = int(entity_map["entity_id"].nunique())
    write_meta(ENTITY_MAP_PATH, **meta)

    _append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": "merge",
            "from_entity": source,
            "to_entity": target,
            "records": sorted(src_records),
            "reason": reason,
            "actor": actor,
            "forced": force,
        }
    )
    print(f"Merge {source} -> {target} ({len(src_records)} record pindah)")
    print(f"  master rows rebuilt: {touched}")
    print(f"  audit: {HISTORY_PATH.name}")


def show_history(entity: str | None) -> None:
    if not HISTORY_PATH.exists():
        print("Belum ada riwayat koreksi entity.")
        return
    rows = [json.loads(line) for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if entity:
        rows = [r for r in rows if r.get("from_entity") == entity or r.get("to_entity") == entity or entity in r.get("records", [])]
    if not rows:
        print("Tidak ada koreksi yang cocok.")
        return
    print(pd.DataFrame(rows).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Split/merge entities with audit history.")
    parser.add_argument("--split", metavar="ENTITY", help="Entity to pull records out of")
    parser.add_argument("--records", nargs="+", help="record_ids to move out (with --split)")
    parser.add_argument("--merge", nargs=2, metavar="ENTITY", help="Two entities to combine")
    parser.add_argument("--reason", default="", help="Why (goes into the audit log)")
    parser.add_argument("--actor", default="reviewer", help="Who decided")
    parser.add_argument("--force", action="store_true", help="Bypass the device/MATCH guard")
    parser.add_argument("--history", action="store_true", help="Print the audit log")
    parser.add_argument("--entity", default=None, help="Filter --history by entity")
    args = parser.parse_args()

    if args.history:
        show_history(args.entity)
        return
    if args.split:
        if not args.records:
            raise SystemExit("--split butuh --records rec_x rec_y ...")
        split(args.split, args.records, args.reason, args.actor, args.force)
        return
    if args.merge:
        merge(args.merge[0], args.merge[1], args.reason, args.actor, args.force)
        return
    parser.print_help()


if __name__ == "__main__":
    main()
