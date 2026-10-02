"""Incremental linkage: dedupe a new batch, then link it to existing entities.

Full re-run (src.run_all) re-standardizes, re-blocks, re-scores, re-clusters and
re-masters every record on every upload. The old data has not changed, so that is
wasteful at production scale. This module does the production flow (PRD FR-14):

    new batch -> standardize -> score (new x new + new x old) -> cluster
    (existing entities are fixed components) -> update master -> review queue

The saved model scores the new pairs; nothing is retrained. Existing entity_ids
are preserved and new entities continue the numbering, so the result for the new
records matches what a full re-run would produce.

Two modes:
  (default) compute and apply in one run.
  --stage     compute and write a staging file, apply nothing. A human reviews
              the proposed merges in the Streamlit batch page first.
  --apply     read the staging file and apply the approved merges.

Known inefficiency: the Splink Linker scores old x old pairs too (they are
filtered out afterwards). That cost is bounded by the full dataset size (~6 s on
51k rows) regardless of new batch size, so it is accepted rather than building a
manual candidate scorer.

Usage:
    python -m src.incremental                      # newest registered batch
    python -m src.incremental --batch batch_0006.csv
    python -m src.incremental --date-order dmy
    python -m src.incremental --stage              # propose, don't apply
    python -m src.incremental --apply              # apply a staged proposal
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

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
    predictions_path,
    write_meta,
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
from .splink_model import add_decision
from .standardize import standardize

HISTORY_PATH = OUTPUT_DIR / "incremental_history.jsonl"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
STAGING_DIR = OUTPUT_DIR / "staging"


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
    """The scored pairs produced by --stage, kept so --apply can complete the
    predictions file without re-scoring (a re-score would renumber record_id
    ordering and could change the reviewed proposal)."""
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


def score_new_pairs(full_std: pd.DataFrame, new_ids: set[str]) -> pd.DataFrame:
    """Score with the saved model, keep only pairs a new record takes part in."""
    latest = model_lifecycle.latest()
    if latest is None:
        raise SystemExit("No saved model. Run python -m src.run_all first.")
    model = model_lifecycle.load_model_json(latest)
    print(f"Scoring with model {latest.name} (no retrain)...")
    linker = Linker(full_std, model, db_api=DuckDBAPI())
    preds = add_decision(linker.inference.predict().as_pandas_dataframe())
    new_preds = preds[
        preds["record_id_l"].isin(new_ids) | preds["record_id_r"].isin(new_ids)
    ].copy()
    print(f"Pairs involving the new batch: {len(new_preds):,} of {len(preds):,} scored")
    return new_preds


def incremental_cluster(
    existing_map: pd.DataFrame, new_ids: set[str], match_edges: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict], int]:
    """Union-find where existing entities are pre-formed components.

    A new record that matches an old record joins that entity. A new record that
    matches records from two entities merges them (the lower entity_id wins, the
    same rule a full re-run's connected-components uses). New records that match
    nothing form new entities, numbered after the current maximum.
    """
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
    """Rebuild master rows for the entities an upload touched."""
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
    """Append the new batch's REVIEW pairs; existing labels are carried forward."""
    review = new_preds[new_preds["decision"] == "REVIEW"].copy()
    if review.empty:
        return 0
    review = agree_fields(full_std, review)
    # agree_fields projects only the agree_* flags, so the score is merged back.
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
    """Standardize, score and cluster without writing any shared artifact."""
    new_std = standardize_new_batch(batch, date_order)
    new_ids = set(new_std["record_id"])

    old_std = pd.read_parquet(PROCESSED_DATA_PATH)
    overlap = new_ids & set(old_std["record_id"])
    if overlap:
        raise SystemExit(
            f"{batch['file']} is already in the standardized parquet "
            f"({len(overlap):,} record_ids overlap). Incremental is not idempotent: "
            "use a new batch, or run python -m src.run_all for a full rebuild."
        )
    full_std = pd.concat([old_std, new_std], ignore_index=True)

    new_preds = score_new_pairs(full_std, new_ids)
    match_edges = new_preds[new_preds["decision"] == "MATCH"]
    n_review = int((new_preds["decision"] == "REVIEW").sum())
    print(
        f"New-batch decisions: MATCH={len(match_edges):,} REVIEW={n_review:,} "
        f"NON_MATCH={int((new_preds['decision'] == 'NON_MATCH').sum()):,}"
    )

    existing_map = pd.read_parquet(ENTITY_MAP_PATH)
    updated_map, merge_events, n_new = incremental_cluster(
        existing_map, new_ids, match_edges
    )
    frame = full_std.merge(updated_map, on="record_id", how="inner")
    new_entity_of = dict(zip(updated_map["record_id"], updated_map["entity_id"]))
    affected = {new_entity_of[rid] for rid in new_std["record_id"]}
    for event in merge_events:
        affected.update(event["entities"])
    return {
        "batch": batch,
        "new_std": new_std,
        "new_ids": new_ids,
        "full_std": full_std,
        "new_preds": new_preds,
        "match_edges": match_edges,
        "updated_map": updated_map,
        "merge_events": merge_events,
        "n_new": n_new,
        "frame": frame,
        "affected": affected,
    }


def build_staging_rows(state: dict) -> pd.DataFrame:
    """One row per new record: what the system proposes to do with it."""
    new_std = state["new_std"]
    new_preds = state["new_preds"]
    updated_map = state["updated_map"]
    entity_of = dict(zip(updated_map["record_id"], updated_map["entity_id"]))

    # Best match edge per new record (highest probability) for context.
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
            pd.read_parquet(ENTITY_MAP_PATH)["entity_id"]
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
    """Write the computed result to the shared artifacts."""
    batch = state["batch"]
    new_std = state["new_std"]
    full_std = state["full_std"]
    new_preds = state["new_preds"]
    updated_map = state["updated_map"]
    merge_events = state["merge_events"]
    n_new = state["n_new"]
    frame = state["frame"]
    affected = state["affected"]

    full_std.to_parquet(PROCESSED_DATA_PATH, index=False)
    write_meta(
        PROCESSED_DATA_PATH,
        artifact="standardized_records",
        rows=len(full_std),
        source_files=[b["file"] for b in registry.load()["batches"]],
        incremental_batch=batch["file"],
    )

    preds_path = predictions_path(full=True)
    if preds_path.exists():
        existing_preds = pd.read_parquet(preds_path)
        combined_preds = pd.concat([existing_preds, new_preds], ignore_index=True)
        combined_preds.to_parquet(preds_path, index=False)
        # Without this the predictions sidecar keeps describing the last TRAINING
        # run, so evaluate/dashboard report a stale row count and a null
        # model_version after every incremental batch.
        active = model_lifecycle.latest()
        write_meta(
            preds_path,
            artifact="splink_predictions",
            scope=SCOPE_FULL,
            input_rows=len(full_std),
            pairs_scored=len(combined_preds),
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

    master = pd.read_parquet(MASTER_PATH)
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

    n_queue = update_review_queue(new_preds, full_std)

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
        "runtime_seconds": None,  # filled by caller
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
        known = set(pd.read_parquet(ENTITY_MAP_PATH, columns=["record_id"])["record_id"])
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
        # A proposal scored by a different model is stale: its probabilities do not
        # reflect the current one. Re-stage instead of applying a wrong guess.
        if "model_version" in staging.columns:
            staged_model = staging["model_version"].iloc[0]
            current = model_lifecycle.latest()
            current_name = current.name if current else None
            if staged_model != current_name:
                raise SystemExit(
                    f"Staging was scored by {staged_model} but the active model is "
                    f"{current_name}. The proposal is stale — reject it and re-stage:\n"
                    f"  python -m src.incremental --reject\n"
                    f"  python -m src.incremental --stage"
                )
        known = set(pd.read_parquet(ENTITY_MAP_PATH, columns=["record_id"])["record_id"])
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
        # Standardize only (no scoring): the staged proposal already holds the
        # entity assignment a human reviewed. compute() re-scores with the model
        # and would refuse because the batch is not idempotent.
        new_std = standardize_new_batch(batch, explicit)
        apply_staged(new_std, staging, batch)
        return

    state = compute(batch, explicit)

    if args.stage:
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        staging = build_staging_rows(state)
        # Default every record to approved: the batch page only unchecks the ones
        # a reviewer disputes. model_version stamps the proposal so --apply can
        # refuse it after a retrain.
        active = model_lifecycle.latest()
        staging["approved"] = True
        staging["model_version"] = active.name if active else None
        staging.to_parquet(staging_path(batch), index=False)
        # Keep the scored pairs: without them --apply cannot complete the
        # predictions file, and a half-written predictions file makes every later
        # evaluation read a dataset it cannot account for.
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

    print(f"\n{'=' * 60}")
    print(f"Batch {batch['file']} linked in {history['runtime_seconds']}s")
    print(f"  new records: {len(state['new_std']):,} -> {state['n_new']:,} new entities")
    print(f"  entity merges: {len(state['merge_events']):,}")
    print(f"  master rows recomputed: {state['affected'].__len__():,}")
    print(f"  review pairs added: {history['review_pairs_added']:,}")
    print(f"  total entities: {state['updated_map']['entity_id'].nunique():,}")


def apply_staged(new_std: pd.DataFrame, staging: pd.DataFrame, batch: dict) -> None:
    """Apply a human-reviewed staged proposal without re-scoring.

    The staging file already holds the reviewed entity assignment, so this only
    writes artifacts: the batch is appended to the standardized parquet, the
    entity map gains the proposed assignments, and the master rows of every
    affected entity are rebuilt. Predictions for the new records are NOT written
    here: they were produced during --stage and a re-score would renumber
    record_id ordering for the whole file.
    """
    started = time.perf_counter()

    # Start from the staged proposal: record_id -> proposed_entity_id. A record
    # the reviewer did not approve does NOT join the proposed entity: it enters
    # the dataset as its own new entity (records are never silently dropped —
    # AGENTS.md data rules).
    proposal = dict(zip(staging["record_id"], staging["proposed_entity_id"]))
    if "approved" in staging.columns:
        rejected = staging[staging["approved"] == False]  # noqa: E712
        if len(rejected):
            max_entity = max(
                (int(e.split("_")[1]) for e in proposal.values()), default=0
            )
            next_id = max(max_entity, int(
                pd.read_parquet(ENTITY_MAP_PATH, columns=["entity_id"])["entity_id"]
                .str.split("_").str[1].astype(int).max()
            ))
            for rid in rejected["record_id"]:
                next_id += 1
                proposal[rid] = f"ent_{next_id:06d}"
            print(
                f"  {len(rejected):,} record tidak disetujui reviewer — "
                "masuk sebagai entity baru sendiri, tidak digabung."
            )

    # The proposal is a dict of NEW record_ids; mapping it back onto the existing
    # DataFrame would silently drop them (map() only assigns to rows that already
    # exist), which left entity_map short by exactly the batch size and broke the
    # next compute() with a KeyError. New records are appended as rows instead.
    existing_map = pd.read_parquet(ENTITY_MAP_PATH)
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

    old_std = pd.read_parquet(PROCESSED_DATA_PATH)
    full_std = pd.concat([old_std, new_std], ignore_index=True)
    frame = full_std.merge(updated_map, on="record_id", how="inner")
    affected = set(proposal.values())

    full_std.to_parquet(PROCESSED_DATA_PATH, index=False)
    write_meta(
        PROCESSED_DATA_PATH,
        artifact="standardized_records",
        rows=len(full_std),
        source_files=[b["file"] for b in registry.load()["batches"]],
        incremental_batch=batch["file"],
    )
    # Append the pairs scored during --stage. Skipping this leaves the predictions
    # file without the new batch, and the device-truth check then reports pairs it
    # cannot find scored — an artifact that looks like a modelling failure.
    preds_path = predictions_path(full=True)
    staged_preds = staged_preds_path(batch)
    if preds_path.exists() and staged_preds.exists():
        new_pairs = pd.read_parquet(staged_preds)
        existing = pd.read_parquet(preds_path)
        overlap = len(existing) + len(new_pairs)
        combined = pd.concat([existing, new_pairs], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["record_id_l", "record_id_r"], keep="last"
        )
        if len(combined) != overlap:
            print(
                f"  note: {overlap - len(combined):,} pair(s) were already scored; "
                "kept the newer score."
            )
        combined.to_parquet(preds_path, index=False)
        active = model_lifecycle.latest()
        write_meta(
            preds_path,
            artifact="splink_predictions",
            scope=SCOPE_FULL,
            input_rows=len(full_std),
            pairs_scored=len(combined),
            incremental_batch=batch["file"],
            model_version=active.name if active else None,
            match_threshold=MATCH_THRESHOLD,
            review_threshold=REVIEW_THRESHOLD,
            trained=False,
            applied_from_staging=True,
        )
        print(f"  predictions: {len(existing):,} -> {len(combined):,} pairs")
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
    master = pd.read_parquet(MASTER_PATH)
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

    history = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "batch": batch["file"],
        "rows": batch["rows"],
        "new_records": len(new_std),
        "new_entities": int(updated_map["entity_id"].nunique()),
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
