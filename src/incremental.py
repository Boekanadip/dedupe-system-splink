from __future__ import annotations

import argparse
import copy
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
from splink import DuckDBAPI, Linker

from . import model_lifecycle, registry
from .config import (
    ENTITY_MAP_PATH,
    LABELS_DIR,
    MASTER_PATH,
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    PROJECT_ROOT,
    REVIEW_THRESHOLD,
    SCOPE_FULL,
    STAGING_ENV,
    acquire_pipeline_lock,
    active_path,
    discard_staged,
    finalize_staged,
    predictions_path,
    release_pipeline_lock,
    write_meta,
    atomic_write_parquet,
    atomic_write_json,
)
from .labels import (
    QUEUE_PATH,
    REVIEW_FIELDS,
    agree_fields,
    attach_evidence,
    carry_over_reviewed,
)
from .master_record import MASTER_FIELDS, build_lineage, pick_master_values
from .profiling import load_raw
from .splink_model import add_decision, apply_business_rules
from .standardize import standardize

HISTORY_PATH = OUTPUT_DIR / "incremental_history.jsonl"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
STAGING_DIR = OUTPUT_DIR / "staging"


def _rule_key_pairs(model: dict) -> list[list[tuple[str, str]]] | None:

    rules = []
    for rule in model["blocking_rules_to_generate_predictions"]:
        pairs = re.findall(
            r'l\."?([A-Za-z_]\w*)"?\s*=\s*r\."?([A-Za-z_]\w*)"?',
            rule["blocking_rule"],
        )
        if not pairs:
            return None
        rules.append(pairs)
    return rules


def candidate_old_rows(
    new_std: pd.DataFrame, key_pairs: list[list[tuple[str, str]]]
) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("new_batch", new_std)
    exists = " OR ".join(
        "EXISTS (SELECT 1 FROM new_batch n WHERE "
        + " AND ".join(f'n."{left}" = o."{right}"' for left, right in pairs)
        + ")"
        for pairs in key_pairs
    )
    sql = (
        f"SELECT o.* FROM read_parquet('{PROCESSED_DATA_PATH}') o "
        f"WHERE ({exists}) "
        "AND NOT EXISTS (SELECT 1 FROM new_batch n WHERE n.record_id = o.record_id)"
    )
    return con.execute(sql).df()


def _count_parquet(path: Path) -> int:
    if not path.exists():
        return 0
    return int(
        duckdb.connect().execute(
            f"SELECT count(*) FROM read_parquet('{path}')"
        ).fetchone()[0]
    )


def _overlapping_old_record_ids(new_ids: set[str]) -> set[str]:
    """record_id batch baru yang juga ada di parquet tersimpan.

    Linkage inkremental tidak idempoten: menjalankan ulang batch akan mengubah
    nomor dan menghitung data dua kali. Pemeriksaan ini tidak boleh memuat parquet.
    """
    if not active_path(PROCESSED_DATA_PATH).exists():
        return set()
    con = duckdb.connect()
    con.register("new_batch", pd.DataFrame({"record_id": sorted(new_ids)}))
    return set(
        con.execute(
            f"SELECT o.record_id FROM read_parquet('{PROCESSED_DATA_PATH}') o "
            "JOIN new_batch n ON n.record_id = o.record_id"
        ).fetchdf()["record_id"]
    )


def _append_parquet(
    target: Path, extra: pd.DataFrame, dedup_on: tuple[str, ...] | None = None
) -> None:

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    con = duckdb.connect()
    con.register("appended", extra)
    if not target.exists():
        con.execute(f"COPY (SELECT * FROM appended) TO '{tmp}' (FORMAT PARQUET)")
        con.close()
        os.replace(tmp, target)
        return
    if dedup_on:
        keys = " AND ".join(f't."{c}" = a."{c}"' for c in dedup_on)
        extra_sql = (
            "SELECT a.* FROM appended a WHERE NOT EXISTS "
            f"(SELECT 1 FROM read_parquet('{target}') t WHERE {keys})"
        )
    else:
        extra_sql = "SELECT * FROM appended"
    con.execute(
        f"COPY (SELECT * FROM read_parquet('{target}') UNION ALL BY NAME "
        f"{extra_sql}) TO '{tmp}' (FORMAT PARQUET)"
    )
    con.close()
    os.replace(tmp, target)


def _old_rows_by_id(record_ids) -> pd.DataFrame:
    """Ambil baris tersimpan berdasarkan record_id tanpa memuat seluruh parquet."""
    wanted = pd.DataFrame({"record_id": sorted(record_ids)})
    con = duckdb.connect()
    con.register("wanted", wanted)
    return con.execute(
        f"SELECT o.* FROM read_parquet('{PROCESSED_DATA_PATH}') o "
        "JOIN wanted w ON w.record_id = o.record_id"
    ).df()


def resolve_batch(name: str | None) -> dict:
    reg = registry.load()
    if not reg["batches"]:
        raise SystemExit("No batches registered. Upload one from app.py first.")
    if name:
        for batch in reg["batches"]:
            if batch["file"] == name:
                return batch
        raise SystemExit(f"{name} not in the registry")
    return reg["batches"][-1]


def staging_path(batch: dict) -> Path:
    return STAGING_DIR / f"{batch['file']}.parquet"


def staged_preds_path(batch: dict) -> Path:
    return STAGING_DIR / f"{batch['file']}.predictions.parquet"


def standardize_new_batch(batch: dict, date_order: str | None) -> pd.DataFrame:
    raw = load_raw(RAW_DIR / batch["file"])
    evidence: dict = {}
    new_std = standardize(raw, date_order, evidence, start_index=batch["start_index"])
    for canonical, ev in evidence.items():
        print(
            f"{canonical}: day>12 in {ev['day_gt_12']:,}, month>12 in "
            f"{ev['month_gt_12']:,}, ambiguous in {ev['ambiguous_rows']:,} "
            f"-> applied {ev['applied_order']} ({ev['source']})"
        )
    return new_std


def tf_adjusted_columns(model: dict) -> list[str]:

    cols: list[str] = []
    for comparison in model.get("comparisons", []):
        for level in comparison.get("comparison_levels", []):
            col = level.get("tf_adjustment_column")
            if col and col not in cols:
                cols.append(col)
    return cols


def corpus_tf_tables(model: dict) -> dict[str, pd.DataFrame]:

    cols = tf_adjusted_columns(model)
    if not cols:
        return {}
    corpus = pd.read_parquet(PROCESSED_DATA_PATH, columns=cols)
    tables = {}
    for col in cols:
        counts = corpus[col].value_counts(dropna=True)
        tables[col] = pd.DataFrame(
            {col: counts.index, f"tf_{col}": counts.to_numpy() / counts.to_numpy().sum()}
        )
    return tables


def score_new_pairs(
    frame: pd.DataFrame, new_ids: set[str], model: dict | None = None
) -> pd.DataFrame:
    
    latest = model_lifecycle.latest()
    if latest is None:
        raise SystemExit("No saved model. Run python -m src.run_all first.")
    if model is None:
        model = model_lifecycle.load_model_json(latest)
    print(f"Scoring with model {latest.name} (no retrain)...")

    scored = frame.copy()
    scored["is_new"] = scored["record_id"].isin(new_ids)
    patched = copy.deepcopy(model)
    for rule in patched["blocking_rules_to_generate_predictions"]:
        rule["blocking_rule"] = (
            f'({rule["blocking_rule"]}) AND (l.is_new OR r.is_new)'
        )

    db_api = DuckDBAPI()
    sdf = db_api.register_table(scored)
    linker = Linker(sdf, patched)
    tf_tables = corpus_tf_tables(model)
    for col, table in tf_tables.items():
        linker.table_management.register_term_frequency_lookup(table, col, overwrite=True)
    if tf_tables:
        print(
            f"TF adjustments registered from the full corpus for "
            f"{len(tf_tables)} column(s): {', '.join(sorted(tf_tables))}"
        )
    preds = add_decision(linker.inference.predict().as_pandas_dataframe())
    # Aturan bisnis domain juga berlaku di sini: tanpa apply_business_rules,
    # pasangan dari batch baru dengan email+nama+alamat sama tetapi dob berbeda
    # akan digabung otomatis pada jalur inkremental, padahal jalur proses penuh
    # menahannya.
    preds = apply_business_rules(preds)
    new_preds = preds[
        preds["record_id_l"].isin(new_ids) | preds["record_id_r"].isin(new_ids)
    ].copy()
    print(
        f"Pairs involving the new batch: {len(new_preds):,} scored "
        f"(old x old excluded at the blocking stage, not filtered afterwards)"
    )
    return new_preds


def incremental_cluster(
    existing_map: pd.DataFrame, new_ids: set[str], match_edges: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict], int]:

    parent: dict[str, str] = {}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            low, high = sorted((root_a, root_b))
            parent[high] = low

    by_entity: dict[str, list[str]] = defaultdict(list)
    for rid, eid in zip(existing_map["record_id"], existing_map["entity_id"]):
        by_entity[eid].append(rid)
        parent.setdefault(rid, rid)
    for rids in by_entity.values():
        for rid in rids[1:]:
            union(rids[0], rid)
    for rid in new_ids:
        parent[rid] = rid
    for left, right in zip(match_edges["record_id_l"], match_edges["record_id_r"]):
        union(left, right)

    new_groups: dict[str, list[str]] = defaultdict(list)
    for rid in new_ids:
        new_groups[find(rid)].append(rid)
    old_by_root: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for rid, eid in zip(existing_map["record_id"], existing_map["entity_id"]):
        old_by_root[find(rid)].append((rid, eid))

    max_entity = max(
        (int(eid.split("_")[1]) for eid in existing_map["entity_id"]), default=0
    )
    entity_updates: dict[str, str] = {}
    new_rows: list[tuple[str, str]] = []
    merge_events: list[dict] = []
    next_entity = max_entity

    for root in sorted(new_groups, key=lambda r: min(new_groups[r])):
        members = new_groups[root]
        olds = old_by_root.get(root, [])
        if olds:
            target = min(eid for _, eid in olds)
            old_eids = {eid for _, eid in olds}
            if len(old_eids) > 1:
                merge_events.append(
                    {
                        "entities": sorted(old_eids),
                        "into": target,
                        "via_new_records": members,
                    }
                )
            for rid, eid in olds:
                if eid != target:
                    entity_updates[rid] = target
            for rid in members:
                new_rows.append((rid, target))
        else:
            next_entity += 1
            eid = f"ent_{next_entity:06d}"
            for rid in members:
                new_rows.append((rid, eid))

    updated = existing_map.copy()
    emap = dict(zip(updated["record_id"], updated["entity_id"]))
    for rid, eid in entity_updates.items():
        emap[rid] = eid
    updated["entity_id"] = updated["record_id"].map(emap)
    new_df = pd.DataFrame(new_rows, columns=["record_id", "entity_id"])
    updated = pd.concat([updated, new_df], ignore_index=True)
    return updated, merge_events, next_entity - max_entity


def recompute_master_rows(frame: pd.DataFrame, eids: set[str]) -> pd.DataFrame:
    """Bangun ulang baris master untuk entity yang disentuh oleh unggahan."""
    sub = frame[frame["entity_id"].isin(eids)]
    if sub.empty:
        return pd.DataFrame()
    master = build_lineage(sub).merge(pick_master_values(sub), on="entity_id", how="left")
    long = sub.melt(
        id_vars=["entity_id"],
        value_vars=MASTER_FIELDS,
        var_name="field",
        value_name="value",
    ).dropna(subset=["value"])
    conflicts = (
        long.groupby(["entity_id", "field"])["value"]
        .nunique()
        .rename("distinct_values")
        .reset_index()
    )
    conflicted = (
        conflicts[conflicts["distinct_values"] > 1]
        .groupby("entity_id")["field"]
        .apply(lambda s: sorted(s.tolist()))
        .rename("conflicted_fields")
        .reset_index()
    )
    master = master.merge(conflicted, on="entity_id", how="left")
    master["conflicted_fields"] = master["conflicted_fields"].apply(
        lambda v: v if isinstance(v, list) else []
    )
    return master


def update_review_queue(new_preds: pd.DataFrame, full_std: pd.DataFrame) -> int:
    """Tambahkan pasangan REVIEW batch baru; label yang sudah ada tetap dibawa."""
    review = new_preds[new_preds["decision"] == "REVIEW"].copy()
    if review.empty:
        return 0
    review = agree_fields(full_std, review)
    # agree_fields hanya mengambil flag agree_*, sehingga skor digabungkan kembali.
    review = review.merge(
        new_preds[["record_id_l", "record_id_r", "match_probability"]],
        on=["record_id_l", "record_id_r"],
        how="left",
    )
    review = attach_evidence(full_std, review)
    review["stratum"] = "incremental_new_batch"
    review["label"] = None
    review["review_status"] = "pending"
    review["reviewer"] = None
    review["reviewer_note"] = None
    columns = [
        "record_id_l", "record_id_r", "stratum",
        "agree_email", "agree_phone", "agree_dob", "agree_name", "agree_city",
        "match_probability",
        *[f"{f}_{side}" for side in ("l", "r") for f in REVIEW_FIELDS],
        "label", "review_status", "reviewer", "reviewer_note",
    ]
    new_rows = review[columns]
    old_queue = pd.read_csv(QUEUE_PATH) if QUEUE_PATH.exists() else pd.DataFrame()
    combined = pd.concat([old_queue, new_rows], ignore_index=True)
    combined = carry_over_reviewed(combined)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(QUEUE_PATH, index=False)
    return len(new_rows)


def compute(batch: dict, date_order: str | None) -> dict:
    """Standardisasi, beri skor, dan kelompokkan tanpa menulis artefak bersama."""
    new_std = standardize_new_batch(batch, date_order)
    new_ids = set(new_std["record_id"])

    overlap = _overlapping_old_record_ids(new_ids)
    if overlap:
        raise SystemExit(
            f"{batch['file']} is already in the standardized parquet "
            f"({len(overlap):,} record_ids overlap). Incremental is not idempotent: "
            "use a new batch, or run python -m src.run_all for a full rebuild."
        )

    latest = model_lifecycle.latest()
    if latest is None:
        raise SystemExit("No saved model. Run python -m src.run_all first.")
    model = model_lifecycle.load_model_json(latest)
    key_pairs = _rule_key_pairs(model)

    if key_pairs is None:

        print("pre-filter skipped: a blocking rule is not a pure equi-join")
        scoring_frame = pd.concat(
            [pd.read_parquet(active_path(PROCESSED_DATA_PATH)), new_std], ignore_index=True
        )
    elif not active_path(PROCESSED_DATA_PATH).exists():
        scoring_frame = new_std
    else:
        old_candidates = candidate_old_rows(new_std, key_pairs)
        scoring_frame = pd.concat([old_candidates, new_std], ignore_index=True)
        print(
            f"Old rows: {_count_parquet(PROCESSED_DATA_PATH):,} stored, "
            f"{len(old_candidates):,} share a blocking key with the new batch"
        )

    new_preds = score_new_pairs(scoring_frame, new_ids, model=model)
    match_edges = new_preds[new_preds["decision"] == "MATCH"]
    n_review = int((new_preds["decision"] == "REVIEW").sum())
    print(
        f"New-batch decisions: MATCH={len(match_edges):,} REVIEW={n_review:,} "
        f"NON_MATCH={int((new_preds['decision'] == 'NON_MATCH').sum()):,}"
    )

    existing_map = pd.read_parquet(active_path(ENTITY_MAP_PATH))
    updated_map, merge_events, n_new = incremental_cluster(
        existing_map, new_ids, match_edges
    )
    new_entity_of = dict(zip(updated_map["record_id"], updated_map["entity_id"]))
    affected = {new_entity_of[rid] for rid in new_std["record_id"]}
    for event in merge_events:
        affected.update(event["entities"])

    pair_ids = set(new_preds["record_id_l"]) | set(new_preds["record_id_r"])
    pair_frame = scoring_frame[scoring_frame["record_id"].isin(pair_ids)]

    return {
        "batch": batch,
        "new_std": new_std,
        "new_ids": new_ids,
        "new_preds": new_preds,
        "match_edges": match_edges,
        "updated_map": updated_map,
        "merge_events": merge_events,
        "n_new": n_new,
        "pair_frame": pair_frame,
        "old_row_count": _count_parquet(PROCESSED_DATA_PATH),
        "affected": affected,
    }


def build_staging_rows(state: dict) -> pd.DataFrame:
    """Satu baris per catatan baru: usulan tindakan sistem terhadap catatan tersebut."""
    new_std = state["new_std"]
    new_preds = state["new_preds"]
    updated_map = state["updated_map"]
    entity_of = dict(zip(updated_map["record_id"], updated_map["entity_id"]))

    best = (
        new_preds.sort_values("match_probability", ascending=False)
        .drop_duplicates(subset=["record_id_l", "record_id_r"])
    )
    matched_to: dict[str, str] = {}
    for _, row in best.iterrows():
        for side in ("l", "r"):
            other = "r" if side == "l" else "l"
            rid = row[f"record_id_{side}"]
            if rid in state["new_ids"]:
                matched_to[rid] = row[f"record_id_{other}"]

    rows = []
    for _, rec in new_std.iterrows():
        rid = rec["record_id"]
        eid = entity_of[rid]
        is_existing = eid in set(
            pd.read_parquet(active_path(ENTITY_MAP_PATH))["entity_id"]
        )
        if rid in matched_to:
            action = "match"
        elif is_existing:
            action = "match"
        else:
            action = "new"
        rows.append(
            {
                "record_id": rid,
                "customer_id": rec.get("customer_id"),
                "first_name_std": rec.get("first_name_std"),
                "last_name_std": rec.get("last_name_std"),
                "email_std": rec.get("email_std"),
                "phone_std": rec.get("phone_std"),
                "dob_std": rec.get("dob_std"),
                "city_std": rec.get("city_std"),
                "proposed_entity_id": eid,
                "action": action,
                "matched_to": matched_to.get(rid),
                "match_probability": float(
                    best[best["record_id_l"].eq(rid) | best["record_id_r"].eq(rid)][
                        "match_probability"
                    ].max()
                )
                if rid in matched_to
                else None,
            }
        )
    return pd.DataFrame(rows)


def apply(state: dict) -> dict:
    """Tulis hasil perhitungan ke artefak bersama."""
    batch = state["batch"]
    new_std = state["new_std"]
    new_preds = state["new_preds"]
    updated_map = state["updated_map"]
    merge_events = state["merge_events"]
    n_new = state["n_new"]
    affected = state["affected"]

    _append_parquet(PROCESSED_DATA_PATH, new_std)
    write_meta(
        PROCESSED_DATA_PATH,
        artifact="standardized_records",
        rows=state["old_row_count"] + len(new_std),
        source_files=[b["file"] for b in registry.load()["batches"]],
        incremental_batch=batch["file"],
    )

    preds_path = active_path(predictions_path(full=True))
    existing_pairs = _count_parquet(preds_path)
    _append_parquet(preds_path, new_preds)
    active = model_lifecycle.latest()
    write_meta(
        preds_path,
        artifact="splink_predictions",
        scope=SCOPE_FULL,
        input_rows=state["old_row_count"] + len(new_std),
        pairs_scored=existing_pairs + len(new_preds),
        incremental_batch=batch["file"],
        model_version=active.name if active else None,
        match_threshold=MATCH_THRESHOLD,
        review_threshold=REVIEW_THRESHOLD,
        trained=False,
    )

    updated_map.to_parquet(ENTITY_MAP_PATH, index=False)
    write_meta(
        ENTITY_MAP_PATH,
        artifact="entity_map",
        scope=SCOPE_FULL,
        records=len(updated_map),
        entities=int(updated_map["entity_id"].nunique()),
        incremental_batch=batch["file"],
        new_entities=n_new,
        entity_merges=len(merge_events),
    )


    emap = dict(zip(updated_map["record_id"], updated_map["entity_id"]))
    affected_ids = {
        rid for rid, eid in emap.items() if eid in affected
    } - set(new_std["record_id"])
    frame = pd.concat([_old_rows_by_id(affected_ids), new_std], ignore_index=True)
    frame["entity_id"] = frame["record_id"].map(emap)
    master = pd.read_parquet(active_path(MASTER_PATH))
    recomputed = recompute_master_rows(frame, affected)
    if not recomputed.empty:
        master = master[~master["entity_id"].isin(affected)]
        master = pd.concat([master, recomputed], ignore_index=True)
        master.to_parquet(MASTER_PATH, index=False)
        write_meta(
            MASTER_PATH,
            artifact="master_customers",
            scope=SCOPE_FULL,
            entities=len(master),
            records=int(master["record_count"].sum()),
            incremental_batch=batch["file"],
        )

    n_queue = update_review_queue(new_preds, state["pair_frame"])

    history = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "batch": batch["file"],
        "rows": batch["rows"],
        "new_records": len(new_std),
        "new_entities": n_new,
        "entity_merges": merge_events,
        "affected_entities": len(affected),
        "match_edges": len(state["match_edges"]),
        "review_pairs_added": n_queue,
        "runtime_seconds": None,  
    }
    return history


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incrementally link a new batch to existing entities."
    )
    parser.add_argument("--batch", default=None, help="Registered file to process (default: newest)")
    parser.add_argument(
        "--date-order",
        choices=["auto", "dmy", "mdy"],
        default="auto",
        help="Day/month order for ambiguous dates.",
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help="Compute and write a staging file; apply nothing.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply a previously staged proposal.",
    )
    parser.add_argument(
        "--reject",
        action="store_true",
        help="Reject a staged proposal: delete the staging files.",
    )
    args = parser.parse_args()
    explicit = None if args.date_order == "auto" else args.date_order

    started = time.perf_counter()
    batch = resolve_batch(args.batch)

    if args.reject:
        path = staging_path(batch)
        known = set(pd.read_parquet(active_path(ENTITY_MAP_PATH), columns=["record_id"])["record_id"])
        if path.exists():
            staged_ids = set(pd.read_parquet(path, columns=["record_id"])["record_id"])
            if staged_ids & known:
                raise SystemExit(
                    f"{batch['file']} is already applied (records are in the entity "
                    "map). Rejected proposals only work BEFORE apply; use a full "
                    "re-run to undo an applied batch."
                )
        removed = []
        for target in (path, staged_preds_path(batch)):
            if target.exists():
                target.unlink()
                removed.append(target.name)
        if not removed:
            raise SystemExit(f"No staged proposal for {batch['file']} to reject.")
        print(f"Rejected staging for {batch['file']}: removed {', '.join(removed)}")
        print(
            f"Batch {batch['file']} stays registered "
            f"({batch['record_id_range'][0]}..{batch['record_id_range'][1]} reserved); "
            "re-stage it or remove it from the registry to free the record_ids."
        )
        return

    print(f"Batch: {batch['file']} ({batch['rows']:,} rows, {batch['record_id_range'][0]}..{batch['record_id_range'][1]})")

    if args.apply:
        path = staging_path(batch)
        if not path.exists():
            raise SystemExit(f"No staged proposal at {path}. Run with --stage first.")
        staging = pd.read_parquet(path)
        if "model_version" in staging.columns:
            staged_model = staging["model_version"].iloc[0]
            current = model_lifecycle.latest()
            current_name = current.name if current else None
            if staged_model != current_name:
                raise SystemExit(
                    f"Staging was scored by {staged_model} but the active model is "
                    f"{current_name}. The proposal is stale â€” reject it and re-stage:\n"
                    f"  python -m src.incremental --reject\n"
                    f"  python -m src.incremental --stage"
                )
        known = set(pd.read_parquet(active_path(ENTITY_MAP_PATH), columns=["record_id"])["record_id"])
        already = set(staging["record_id"]) & known
        if already:
            raise SystemExit(
                f"{batch['file']} is ALREADY applied "
                f"({len(already):,} of {len(staging):,} record_ids are in the entity map).\n"
                "  Applying again would double-count these records.\n"
                "  Delete the staging file if this batch was applied elsewhere "
                f"(for example a full run): rm outputs/staging/{path.name}\n"
                "  Or use a different batch."
            )

        acquire_pipeline_lock(note=f"incremental apply {batch['file']}")
        try:
            new_std = standardize_new_batch(batch, explicit)
            apply_staged(new_std, staging, batch)
        except BaseException:
            discard_staged()
            raise
        finally:
            release_pipeline_lock()

        finalize_staged()
        return

    acquire_pipeline_lock(note=f"incremental compute {batch['file']}")
    try:
        discard_staged()
        state = compute(batch, explicit)
    except BaseException:
        discard_staged()
        raise
    finally:
        release_pipeline_lock()

    if args.stage:
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        staging = build_staging_rows(state)
        active = model_lifecycle.latest()
        staging["approved"] = True
        staging["model_version"] = active.name if active else None
        staging.to_parquet(staging_path(batch), index=False)
        state["new_preds"].to_parquet(staged_preds_path(batch), index=False)
        counts = staging["action"].value_counts().to_dict()
        print(f"Staged {len(staging):,} records -> {staging_path(batch)}")
        print(f"  proposed: {counts}")
        print("Review it in the Streamlit batch page, then run with --apply.")
        return

    history = apply(state)
    history["runtime_seconds"] = round(time.perf_counter() - started, 2)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(history) + "\n")
    print(f"History appended: {HISTORY_PATH.name}")

    # Commit: tukar semua artefak staging ke path asli sekaligus.
    finalize_staged()

    print(f"\n{'=' * 60}")
    print(f"Batch {batch['file']} linked in {history['runtime_seconds']}s")
    print(f"  new records: {len(state['new_std']):,} -> {state['n_new']:,} new entities")
    print(f"  entity merges: {len(state['merge_events']):,}")
    print(f"  master rows recomputed: {state['affected'].__len__():,}")
    print(f"  review pairs added: {history['review_pairs_added']:,}")
    print(f"  total entities: {state['updated_map']['entity_id'].nunique():,}")


def apply_staged(new_std: pd.DataFrame, staging: pd.DataFrame, batch: dict) -> None:
    """Terapkan usulan staging yang telah ditinjau manusia tanpa menghitung ulang skor.

    Berkas staging sudah menyimpan penetapan entity yang telah ditinjau, sehingga
    fungsi ini hanya menulis artefak: batch ditambahkan ke parquet
    terstandardisasi, peta entity mendapat penetapan yang diusulkan, dan baris
    master setiap entity yang terdampak dibangun ulang. Prediksi yang diberi
    skor saat --stage juga ditambahkan. Menghitung ulang skor akan mengubah
    urutan record_id di seluruh berkas.
    """
    started = time.perf_counter()

    proposal = dict(zip(staging["record_id"], staging["proposed_entity_id"]))
    if "approved" in staging.columns:
        rejected = staging[staging["approved"] == False]  # noqa: E712
        if len(rejected):
            max_entity = max(
                (int(e.split("_")[1]) for e in proposal.values()), default=0
            )
            next_id = max(max_entity, int(
                pd.read_parquet(active_path(ENTITY_MAP_PATH), columns=["entity_id"])["entity_id"]
                .str.split("_").str[1].astype(int).max()
            ))
            for rid in rejected["record_id"]:
                next_id += 1
                proposal[rid] = f"ent_{next_id:06d}"
            print(
                f"  {len(rejected):,} record tidak disetujui reviewer â€” "
                "masuk sebagai entity baru sendiri, tidak digabung."
            )

    existing_map = pd.read_parquet(active_path(ENTITY_MAP_PATH))
    updated = {r: e for r, e in zip(existing_map["record_id"], existing_map["entity_id"])}
    updated.update(proposal)
    updated_map = pd.DataFrame(
        {"record_id": list(updated), "entity_id": list(updated.values())}
    )
    unknown = [rid for rid in proposal if rid not in set(existing_map["record_id"])]
    if len(updated_map) != len(existing_map) + len(unknown):
        raise SystemExit(
            f"Entity map would hold {len(updated_map):,} rows but expected "
            f"{len(existing_map) + len(unknown):,}. Refusing to write a partial map."
        )

    old_row_count = _count_parquet(PROCESSED_DATA_PATH)
    known_old = set(existing_map["record_id"])

    affected = set(proposal.values())
    affected_old_ids = [
        rid for rid, eid in updated.items() if eid in affected and rid in known_old
    ]
    frame = pd.concat([_old_rows_by_id(affected_old_ids), new_std], ignore_index=True)
    frame["entity_id"] = frame["record_id"].map(updated)

    _append_parquet(PROCESSED_DATA_PATH, new_std)
    write_meta(
        PROCESSED_DATA_PATH,
        artifact="standardized_records",
        rows=old_row_count + len(new_std),
        source_files=[b["file"] for b in registry.load()["batches"]],
        incremental_batch=batch["file"],
    )

    preds_path = active_path(predictions_path(full=True))
    staged_preds = staged_preds_path(batch)
    new_pairs = pd.DataFrame()
    if staged_preds.exists():
        new_pairs = pd.read_parquet(staged_preds)
        existing_pairs = _count_parquet(preds_path)
        _append_parquet(preds_path, new_pairs, dedup_on=("record_id_l", "record_id_r"))
        active = model_lifecycle.latest()
        write_meta(
            preds_path,
            artifact="splink_predictions",
            scope=SCOPE_FULL,
            input_rows=old_row_count + len(new_std),
            pairs_scored=existing_pairs + len(new_pairs),
            incremental_batch=batch["file"],
            model_version=active.name if active else None,
            match_threshold=MATCH_THRESHOLD,
            review_threshold=REVIEW_THRESHOLD,
            trained=False,
            applied_from_staging=True,
        )
        print(f"  predictions: {existing_pairs:,} stored, +{len(new_pairs):,} new pairs")
    updated_map.to_parquet(ENTITY_MAP_PATH, index=False)
    write_meta(
        ENTITY_MAP_PATH,
        artifact="entity_map",
        scope=SCOPE_FULL,
        records=len(updated_map),
        entities=int(updated_map["entity_id"].nunique()),
        incremental_batch=batch["file"],
        applied_from_staging=True,
    )
    master = pd.read_parquet(active_path(MASTER_PATH))
    recomputed = recompute_master_rows(frame, affected)
    if not recomputed.empty:
        master = master[~master["entity_id"].isin(affected)]
        master = pd.concat([master, recomputed], ignore_index=True)
        master.to_parquet(MASTER_PATH, index=False)
        write_meta(
            MASTER_PATH,
            artifact="master_customers",
            scope=SCOPE_FULL,
            entities=len(master),
            records=int(master["record_count"].sum()),
            incremental_batch=batch["file"],
        )
    staging_path(batch).unlink(missing_ok=True)
    staged_preds_path(batch).unlink(missing_ok=True)

    if new_pairs.empty:
        print("  review queue: no scored pairs in the staging file")
    else:
        try:
            staged_pair_ids = set(new_pairs["record_id_l"]) | set(
                new_pairs["record_id_r"]
            )
            pair_frame = _old_rows_by_id(staged_pair_ids)
            n_queue = update_review_queue(new_pairs, pair_frame)
            print(f"  review queue: +{n_queue:,} pairs")
        except Exception as exc:
            # Artefak sudah ditulis; kegagalan antrean tidak boleh membatalkan penerapan.
            print(f"  review queue NOT updated: {type(exc).__name__}: {exc}")

    staged_entities = set(proposal.values()) - set(existing_map["entity_id"])
    history = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "batch": batch["file"],
        "rows": batch["rows"],
        "new_records": len(new_std),
        "new_entities": len(staged_entities),
        "entity_merges": [],
        "affected_entities": len(affected),
        "match_edges": int((staging["action"] == "match").sum()),
        "review_pairs_added": 0,
        "runtime_seconds": round(time.perf_counter() - started, 2),
        "applied_from_staging": True,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(history) + "\n")
    print(f"Applied staged proposal for {batch['file']}: {len(proposal):,} records")
    print(f"  entities touched: {len(affected):,}")
    print(f"  master rows rebuilt: {len(recomputed):,}")
    print(f"  total entities: {updated_map['entity_id'].nunique():,} (in {history['runtime_seconds']}s)")


if __name__ == "__main__":
    main()
