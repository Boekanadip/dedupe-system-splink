"""Measure what happens to old entities when a new batch is added.

Four numbers, and what each one actually answers:

1. cross_batch_match_pairs   - did the model link records across batches at all?
                               A value of 0 would mean "new rows are a separate
                               island", i.e. the linkage is not incremental.
2. new_batch_internal_pairs   - duplicates found inside the new batch only.
3. wrong_merges               - cross-batch edges the silver labels call
                               negative (contradicting dob/name evidence). The
                               measure of damage done to old entities.
4. old_entity_ids_changed     - records from the old batch whose entity_id moved
                               between the baseline run and the combined run.

The 4th one is the real risk: `connected_components` numbers entities from the
lowest record_id in each component, so appending records *can* renumber the
old ones. That is a structural property of the clustering step, not a modelling
result, so it is measured here rather than assumed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .config import ENTITY_MAP_PATH, LABELS_DIR, MATCH_THRESHOLD, OUTPUT_DIR, predictions_path

BASELINE_PATH = OUTPUT_DIR / "entity_map_batch1.parquet"
REPORT_PATH = OUTPUT_DIR / "batch_linkage_report.json"

NEW_BATCH_FIRST_RECORD_ID = "rec_040001"  # first row of batch_0002.csv


def _load(path, columns=None):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not found. Run the baseline first.")
    return pd.read_parquet(path, columns=columns)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure cross-batch linkage and old-entity stability."
    )
    parser.add_argument("--baseline", default=str(BASELINE_PATH), help="entity_map of the old batch")
    parser.add_argument("--first-record-id", default=NEW_BATCH_FIRST_RECORD_ID)
    args = parser.parse_args()

    preds_path = predictions_path(full=True)
    preds = pd.read_parquet(preds_path)[["record_id_l", "record_id_r", "match_probability"]]
    edges = preds[preds["match_probability"] >= MATCH_THRESHOLD]

    boundary = args.first_record_id
    in_new = edges["record_id_l"] >= boundary
    cross = edges[in_new != (edges["record_id_r"] >= boundary)]
    new_internal = edges[in_new & (edges["record_id_r"] >= boundary)]

    silver = pd.read_csv(LABELS_DIR / "silver_pairs.csv")
    negatives = silver[silver["label"] == 0][["record_id_l", "record_id_r"]]
    wrong = cross.merge(negatives, on=["record_id_l", "record_id_r"], how="inner")

    baseline = _load(args.baseline, ["record_id", "entity_id"])
    combined = _load(ENTITY_MAP_PATH, ["record_id", "entity_id"])
    old_ids = baseline["record_id"]
    comparison = old_ids.to_frame().merge(baseline, on="record_id").merge(
        combined, on="record_id", suffixes=("_baseline", "_combined")
    )
    changed = int(
        (comparison["entity_id_baseline"] != comparison["entity_id_combined"]).sum()
    )

    # Does membership drift even when the label keeps its name? A record leaving
    # one old entity for another old entity would keep both counts stable while
    # destroying an entity, so compare the sets, not just the ids.
    base_membership = baseline.set_index("record_id")["entity_id"].to_dict()
    comb_membership = combined.set_index("record_id")["entity_id"].to_dict()
    drifted = sum(
        1
        for rid, eid in base_membership.items()
        if comb_membership.get(rid) is not None and comb_membership[rid] != eid
    )

    report = {
        "scope": "full",
        "new_batch_first_record_id": boundary,
        "match_threshold": MATCH_THRESHOLD,
        "total_match_edges": len(edges),
        "cross_batch_match_pairs": len(cross),
        "new_batch_internal_pairs": len(new_internal),
        "old_batch_internal_pairs": int(len(edges) - len(cross) - len(new_internal)),
        "wrong_merges": len(wrong),
        "wrong_merges_definition": (
            "cross-batch match edges whose pair is a silver negative "
            "(conflicting dob/name evidence). Not a human-reviewed judgement."
        ),
        "old_entity_ids_changed": changed,
        "old_records_drifted_between_entities": drifted,
        "baseline_records": len(baseline),
        "combined_records": len(combined),
        "baseline_entities": int(baseline["entity_id"].nunique()),
        "combined_entities": int(combined["entity_id"].nunique()),
        "note": (
            "entity_id is derived from the lowest record_id in a component. Appending "
            "records with HIGHER ids cannot renumber components that already existed; "
            "this report measures it rather than relying on that argument."
        ),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Match edges (p >= {MATCH_THRESHOLD}): {report['total_match_edges']:,}")
    print(f"  cross-batch (batch_0001 <-> batch_0002): {report['cross_batch_match_pairs']:,}")
    print(f"  new batch internal                   : {report['new_batch_internal_pairs']:,}")
    print(f"  old batch internal                   : {report['old_batch_internal_pairs']:,}")
    print(f"Wrong merges (cross-batch silver-negative): {report['wrong_merges']:,}")
    print(f"Old records whose entity_id changed    : {changed:,} of {len(baseline):,}")
    print(f"Old records moved between entities     : {drifted:,} of {len(baseline):,}")
    print(f"Entities: {report['baseline_entities']:,} (baseline) -> "
          f"{report['combined_entities']:,} (combined)")
    print(f"Saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()