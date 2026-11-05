from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

from . import model_lifecycle
from .config import (
    ENTITY_MAP_PATH,
    MASTER_PATH,
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    REVIEW_THRESHOLD,
    SCOPE_FULL,
    acquire_pipeline_lock,
    atomic_write_json,
    predictions_path,
    read_meta,
    release_pipeline_lock,
    write_meta,
)
from .db_export import register_frame
from .db_source import fetch, read_watermark, write_watermark
from .incremental import _rule_key_pairs, candidate_old_rows, score_new_pairs
from .labels import QUEUE_COLUMNS, QUEUE_PATH, attach_evidence, carry_over_reviewed
from .standardize import standardize
from .validate_upload import validate

KEY_MAP_PATH = OUTPUT_DIR.parent / "data" / "processed" / "record_key_map.json"
REFRESH_REPORT = OUTPUT_DIR / "db_refresh_report.json"
STALE_PATH = OUTPUT_DIR / "db_stale_entities.json"

RAW_TRACKED = [
    "first_name", "last_name", "address", "city", "state", "country",
    "email", "phone_number", "dob", "signup_date", "device_id",
]


def load_key_map() -> dict:
    """customer_pk -> record_id for rows that already entered the parquet."""
    if not KEY_MAP_PATH.exists():
        return {}
    return json.loads(KEY_MAP_PATH.read_text(encoding="utf-8"))


def save_key_map(mapping: dict) -> None:
    KEY_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = KEY_MAP_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    os.replace(tmp, KEY_MAP_PATH)


def _pk_str(value) -> str | None:

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def sync_key_map_from_parquet(mapping: dict) -> dict:

    if not PROCESSED_DATA_PATH.exists():
        return mapping
    try:
        rows = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id", "customer_pk"])
    except Exception:
        return mapping  # no customer_pk column in this parquet
    rows = rows.dropna(subset=["customer_pk"])
    for pk, rid in zip(rows["customer_pk"], rows["record_id"]):
        key = _pk_str(pk)
        if key is not None:
            mapping[key] = rid
    return mapping


def _existing_record_ids(record_ids: list[str]) -> set[str]:
    """Which of these record_ids are actually in the standardized parquet."""
    con = duckdb.connect()
    con.register("wanted", pd.DataFrame({"record_id": sorted(record_ids)}))
    found = con.execute(
        f"SELECT o.record_id FROM read_parquet('{PROCESSED_DATA_PATH}') o "
        "JOIN wanted w ON w.record_id = o.record_id"
    ).df()
    con.close()
    return set(found["record_id"])


def _replace_rows(target: Path, replacement: pd.DataFrame) -> None:

    ids = sorted(replacement["record_id"].unique())
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    con = duckdb.connect()
    con.register("replacement", replacement)
    con.register("drop_ids", pd.DataFrame({"record_id": ids}))
    keys = ", ".join(f"'{i}'" for i in ids)
    con.execute(
        f"COPY ("
        f"  SELECT * FROM read_parquet('{target}') "
        f"  WHERE record_id NOT IN ({keys}) "
        f"  UNION ALL BY NAME "
        f"  SELECT * FROM replacement"
        f") TO '{tmp}' (FORMAT PARQUET)"
    )
    con.close()
    os.replace(tmp, target)


def _old_match_edges(record_ids: set[str]) -> pd.DataFrame:
    """Previous MATCH pairs touching any of these record_ids."""
    preds = predictions_path(full=True)
    if not preds.exists():
        return pd.DataFrame()
    con = duckdb.connect()
    con.register("wanted", pd.DataFrame({"record_id": sorted(record_ids)}))
    edges = con.execute(
        f"SELECT record_id_l, record_id_r, match_probability "
        f"FROM read_parquet('{preds}') "
        "WHERE decision = 'MATCH' AND ("
        "  record_id_l IN (SELECT record_id FROM wanted) OR "
        "  record_id_r IN (SELECT record_id FROM wanted)"
        ")"
    ).df()
    con.close()
    return edges


def update_records(
    updates: pd.DataFrame, date_order: str | None, mapping: dict
) -> dict:

    record_ids = [mapping[_pk_str(pk)] for pk in updates["customer_pk"]]
    present = _existing_record_ids(record_ids)
    missing = [rid for rid, pk in zip(record_ids, updates["customer_pk"]) if rid not in present]
    if missing:
        raise SystemExit(
            f"{len(missing)} record_id(s) in the key map are not in the standardized "
            f"parquet: {missing[:5]}... The map is stale; re-run --sync-map or check "
            "the registry."
        )

    evidence: dict = {}
    new_std = standardize(updates.copy(), date_order, evidence)
    new_std["record_id"] = record_ids
    new_std["customer_pk"] = updates["customer_pk"].values

    # Old values, for the change report and to detect which fields moved.
    con = duckdb.connect()
    con.register("wanted", pd.DataFrame({"record_id": record_ids}))
    old_rows = con.execute(
        f"SELECT * FROM read_parquet('{PROCESSED_DATA_PATH}') "
        "JOIN wanted w USING (record_id)"
    ).df()
    con.close()

    changed_fields = _changed_fields(old_rows, updates, record_ids)

    latest = model_lifecycle.latest()
    if latest is None:
        raise SystemExit("No saved model. Run python -m src.run_all first.")
    model = model_lifecycle.load_model_json(latest)
    key_pairs = _rule_key_pairs(model)
    old_edges_before = _old_match_edges(set(record_ids))

    if key_pairs is None:
        scoring_frame = pd.concat(
            [pd.read_parquet(PROCESSED_DATA_PATH), new_std], ignore_index=True
        ).drop_duplicates(subset=["record_id"], keep="last")
    else:
        old_candidates = candidate_old_rows(new_std, key_pairs)
        scoring_frame = pd.concat([old_candidates, new_std], ignore_index=True)
    new_preds = score_new_pairs(scoring_frame, set(record_ids), model=model)

    _replace_rows(PROCESSED_DATA_PATH, new_std)
    write_meta(
        PROCESSED_DATA_PATH,
        artifact="standardized_records",
        rows=len(pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id"])),
        incremental_batch="db_refresh",
    )

    from .incremental import _append_parquet

    _append_parquet(
        predictions_path(full=True), new_preds, dedup_on=("record_id_l", "record_id_r")
    )
    write_meta(
        predictions_path(full=True),
        artifact="splink_predictions",
        scope=SCOPE_FULL,
        incremental_batch="db_refresh",
        model_version=latest.name,
        match_threshold=MATCH_THRESHOLD,
        review_threshold=REVIEW_THRESHOLD,
        trained=False,
    )

    new_edges = new_preds[new_preds["decision"] == "MATCH"][
        ["record_id_l", "record_id_r", "match_probability"]
    ]
    # Opsi B: Recompute komponen yang tersentuh saja (tidak hanya tandai stale).
    recompute_summary = _recompute_affected_entities(
        set(record_ids),
        new_edges,
        predictions_path(full=True),
        ENTITY_MAP_PATH,
        MASTER_PATH,
    )

    return {
        "updated_records": len(record_ids),
        "changed_fields": changed_fields,
        "new_match_edges": len(new_edges),
        "lost_match_edges": len(old_edges_before) - len(
            set(map(tuple, old_edges_before[["record_id_l", "record_id_r"]].values))
            & set(map(tuple, new_edges[["record_id_l", "record_id_r"]].values))
        ) if len(old_edges_before) else 0,
        "stale_entities": recompute_summary["affected_entities"],
        "record_ids": record_ids,
        "recompute": recompute_summary,
    }


def _changed_fields(old_rows: pd.DataFrame, updates: pd.DataFrame, record_ids: list[str]) -> dict:
    """Which tracked raw fields moved, per record. Powers the change report."""
    old_by_id = old_rows.set_index("record_id") if len(old_rows) else pd.DataFrame()
    out: dict[str, list[str]] = {}
    for pk, rid in zip(updates["customer_pk"], record_ids):
        if rid not in old_by_id.index:
            continue
        moved = []
        for col in RAW_TRACKED:
            if col not in updates.columns or col not in old_by_id.columns:
                continue
            new_val = updates.loc[updates["customer_pk"] == pk, col]
            if new_val.empty:
                continue
            new_val = new_val.iloc[0]
            old_val = old_by_id.loc[rid, col]
            if _norm(new_val) != _norm(old_val):
                moved.append(col)
        if moved:
            out[rid] = moved
    return out


def _norm(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def _stale_entities(
    old_edges: pd.DataFrame, new_edges: pd.DataFrame, record_ids: set[str]
) -> list[dict]:
    """Records whose MATCH partners changed — entity membership may be stale."""
    def pairs(df: pd.DataFrame) -> set[tuple]:
        if df.empty:
            return set()
        return set(map(tuple, df[["record_id_l", "record_id_r"]].values))

    old_set, new_set = pairs(old_edges), pairs(new_edges)
    lost = old_set - new_set
    gained = new_set - old_set
    stale_records = set()
    for a, b in lost | gained:
        if a in record_ids:
            stale_records.add(a)
        if b in record_ids:
            stale_records.add(b)
    if not stale_records:
        return []
    emap = pd.read_parquet(ENTITY_MAP_PATH)
    by_rec = dict(zip(emap["record_id"], emap["entity_id"]))
    return [
        {"record_id": r, "entity_id": by_rec.get(r), "reason": "match edges changed"}
        for r in sorted(stale_records)
    ]


def _recompute_affected_entities(
    record_ids: set[str],
    new_edges: pd.DataFrame,
    preds_path: Path,
    emap_path: Path,
    master_path: Path,
) -> dict:
    """Hitung ulang entity yang tersentuh update-in-place, lalu simpan ulang.

    Menggantikan pendekatan lama yang hanya menandai entity sebagai "stale":
    entity_map dan master_customers langsung diperbarui dari MATCH edge terbaru.
    Grafik dipecah ulang per komponen yang tersentuh saja, bukan seluruh dataset.
    """
    from .master_record import build_lineage, pick_master_values

    emap_path, master_path = Path(emap_path), Path(master_path)
    emap = pd.read_parquet(emap_path)
    by_rec = dict(zip(emap["record_id"], emap["entity_id"]))
    touched = {by_rec[rid] for rid in record_ids if rid in by_rec}

    # Record seeds: seluruh anggota entity lama yang tersentuh. Komponen baru
    # dihitung dengan incremental_cluster, yang hanya meng-union record baru
    # ke entity lama lewat MATCH edge.
    seeds = set(record_ids)
    for rid, eid in by_rec.items():
        if eid in touched:
            seeds.add(rid)

    updated_map, merge_events, n_new = incremental_cluster(
        emap, seeds, new_edges[["record_id_l", "record_id_r"]]
    )
    updated_map.to_parquet(emap_path, index=False)
    write_meta(
        emap_path,
        artifact="entity_map",
        scope=SCOPE_FULL,
        records=len(updated_map),
        entities=int(updated_map["entity_id"].nunique()),
        incremental_batch="db_refresh",
    )

    # Perbarui master_customers untuk entity yang tersentuh. Baris lama dihapus
    # dan dibangun ulang dari record + entity_map terbaru, bukan dari baris
    # master lama: entity yang dipecah/merge harus hilang sepenuhnya.
    affected = touched | {e for ev in merge_events for e in ev["entities"]}
    rebuilt = 0
    if master_path.exists() and affected:
        new_map = dict(zip(updated_map["record_id"], updated_map["entity_id"]))
        rows = _old_rows_by_ids({r for r, e in new_map.items() if e in affected})
        if not rows.empty:
            rows["entity_id"] = rows["record_id"].map(new_map)
            rebuilt_frame = build_lineage(rows).merge(
                pick_master_values(rows), on="entity_id", how="left"
            )
            rebuilt = int(rebuilt_frame["entity_id"].nunique())
            master = pd.read_parquet(master_path)
            master = master[~master["entity_id"].isin(affected)]
            master = pd.concat([master, rebuilt_frame], ignore_index=True)
            master.to_parquet(master_path, index=False)
            write_meta(
                master_path,
                artifact="master_customers",
                scope=SCOPE_FULL,
                entities=len(master),
                records=int(master["record_count"].sum()),
                incremental_batch="db_refresh",
            )

    return {
        "affected_entities": len(affected),
        "entities_updated": int(updated_map["entity_id"].nunique()),
        "new_entities": n_new,
        "merged_entities": len(merge_events),
        "master_rows_rebuilt": rebuilt,
    }


def _old_rows_by_ids(record_ids: set[str]) -> pd.DataFrame:
    """Ambil baris parquet berdasarkan record_id tanpa memuat seluruh berkas."""
    ids = sorted(record_ids)
    if not ids:
        return pd.DataFrame()
    con = duckdb.connect()
    con.register("wanted", pd.DataFrame({"record_id": ids}))
    rows = con.execute(
        f"SELECT o.* FROM read_parquet('{PROCESSED_DATA_PATH}') o "
        "JOIN wanted w ON w.record_id = o.record_id"
    ).df()
    con.close()
    return rows

def _write_stale(stale: list[dict]) -> None:
    existing = json.loads(STALE_PATH.read_text(encoding="utf-8")) if STALE_PATH.exists() else []
    seen = {e["record_id"] for e in existing}
    existing.extend(s for s in stale if s["record_id"] not in seen)
    atomic_write_json(existing, STALE_PATH)


def _enqueue_stale(stale: list[dict]) -> int:

    if not stale:
        return 0
    records = pd.read_parquet(PROCESSED_DATA_PATH)
    emap = pd.read_parquet(ENTITY_MAP_PATH)
    by_rec = dict(zip(emap["record_id"], emap["entity_id"]))
    rows = []
    for entry in stale:
        rid = entry["record_id"]
        row = records[records["record_id"] == rid]
        if row.empty:
            continue
        row = row.iloc[0]
        rows.append({
            "record_id_l": rid,
            "record_id_r": rid,
            "stratum": "db_refresh_stale_entity",
            "agree_email": None,
            "agree_phone": None,
            "agree_dob": None,
            "agree_name": None,
            "agree_city": None,
            "match_probability": None,
            "label": None,
            "review_status": "pending",
            "reviewer": None,
            "reviewer_note": (
                f"entity {entry.get('entity_id')} may be stale: {entry.get('reason')}. "
                "Decide whether this record still belongs to that entity."
            ),
        })
    if not rows:
        return 0
    new = pd.DataFrame(rows)
    new = attach_evidence(records, new)
    for col in QUEUE_COLUMNS:
        if col not in new.columns:
            new[col] = None
    new = new[QUEUE_COLUMNS]
    queue = pd.read_csv(QUEUE_PATH) if QUEUE_PATH.exists() else pd.DataFrame(columns=QUEUE_COLUMNS)
    existing = set(zip(queue["record_id_l"].astype(str), queue["record_id_r"].astype(str)))
    new = new[~new.apply(lambda r: (str(r["record_id_l"]), str(r["record_id_r"])) in existing, axis=1)]
    if new.empty:
        return 0
    combined = pd.concat([queue, new], ignore_index=True)
    combined = carry_over_reviewed(combined)
    combined.to_csv(QUEUE_PATH, index=False)
    return len(new)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update already-ingested records when the source row changed."
    )
    parser.add_argument("--source", required=True, help="DSN or path to the database.")
    parser.add_argument("--table", required=True, help="Table or view to read.")
    parser.add_argument(
        "--date-order", choices=["auto", "dmy", "mdy"], default="auto",
        help="Day/month order for ambiguous dates.",
    )
    parser.add_argument(
        "--sync-map",
        action="store_true",
        help="Only rebuild the customer_pk -> record_id map from the parquet, then exit.",
    )
    parser.add_argument(
        "--inserts-only",
        action="store_true",
        help="Only ingest new customer_pk as a batch; skip update-in-place.",
    )
    args = parser.parse_args()
    date_order = None if args.date_order == "auto" else args.date_order

    mapping = sync_key_map_from_parquet(load_key_map())

    if args.sync_map:
        save_key_map(mapping)
        print(f"Key map rebuilt: {len(mapping):,} customer_pk -> record_id entries")
        return

    started = time.perf_counter()

    acquire_pipeline_lock(note=f"db_refresh {args.table}")
    try:
        watermark = read_watermark(args.source, args.table)
        frame = fetch(args.source, args.table, watermark=watermark)
        if frame.empty:
            print("0 changed rows. Nothing to do.")
            return
        if "customer_pk" not in frame.columns:
            raise SystemExit(
                "The table has no customer_pk column, so update-in-place is impossible. "
                "Use src.db_export for a plain ingest, or add a stable primary key."
            )

        # --- G3: validate DB schema against config before proceeding ---
        val = validate(frame)
        if val["blocking"]:
            raise SystemExit(
                f"Batch rejected by schema validation: {'; '.join(val['blocking'])}"
            )
        if val["warnings"]:
            print(f"\nWarnings (still accepted, but lower recall):")
            for reason in val["warnings"]:
                print(f"  ! {reason}")

        pks = frame["customer_pk"].map(_pk_str)
        is_update = pks.isin(mapping.keys())
        inserts, updates = frame[~is_update], frame[is_update]
        print(f"Changed rows: {len(frame):,} -> {len(inserts):,} new, {len(updates):,} update")

        report: dict = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "source": args.source,
            "table": args.table,
            "changed_rows": len(frame),
            "new_rows": len(inserts),
            "update_rows": len(updates),
            "steps": [],
        }

        if len(inserts):
            registered = register_frame(inserts)
            if registered["status"] == "exported":
                print(f"  inserts registered as batch {registered['batch_id']} ({registered['batch_file']})")
                report["steps"].append({"step": "inserts", **registered})
                report["insert_batch"] = registered["batch_file"]
            elif registered["status"] == "already_registered":
                print(f"  {registered['message']}")
                report["steps"].append({"step": "inserts", **registered})
                report["insert_batch"] = registered["batch_file"]

        # --- updates: in place
        if len(updates) and not args.inserts_only:
            print(f"\n== update-in-place ({len(updates):,} records)")
            result = update_records(updates, date_order, mapping)
            report["steps"].append({"step": "updates", **result})
            print(f"  {result['updated_records']:,} records updated")
            print(f"  changed fields: {result['changed_fields']}")
            print(f"  new match edges: {result['new_match_edges']:,}, stale entities: {result['stale_entities']:,}")
            if result["stale_entities"]:
                print(f"  -> {result['stale_entities']} entity/entities may be stale; see {STALE_PATH.name}")

        mapping = sync_key_map_from_parquet(load_key_map())
        save_key_map(mapping)
        last_updated = str(frame.iloc[-1]["updated_at"])
        write_watermark(args.source, args.table, {"updated_at": last_updated})

        report["key_map_size"] = len(mapping)
        report["status"] = "succeeded"
        report["total_seconds"] = round(time.perf_counter() - started, 2)
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(report, REFRESH_REPORT)
        print(f"\nReport: {REFRESH_REPORT}")
    finally:
        release_pipeline_lock()


if __name__ == "__main__":
    main()