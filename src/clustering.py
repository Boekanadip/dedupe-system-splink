from __future__ import annotations

import argparse
import time

import pandas as pd

from .config import (
    ENTITY_MAP_PATH,
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    REVIEW_THRESHOLD,
    SCOPE_FULL,
    predictions_path,
    read_meta,
    scope_of,
    write_meta,
)

CLUSTER_SUMMARY_PATH = OUTPUT_DIR / "cluster_summary.csv"


def load_predictions(full: bool) -> pd.DataFrame:
    path = predictions_path(full=full)
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} not found. Run: python -m src.splink_model"
            + (" --full" if full else "")
        )
    return pd.read_parquet(path)


def guard_against_scope_downgrade(full: bool, force: bool) -> None:
    """Refuse to replace a full-run entity map with a sample-run one.

    A sample run still emits all 50,000 record_ids, so every downstream length
    check passes and nothing looks wrong. What actually changed is that 49,850
    records became singletons because their match edges were never scored.
    """
    existing = read_meta(ENTITY_MAP_PATH)
    if not existing or force:
        return

    new_scope = scope_of(full)
    old_scope = existing.get("scope")
    if old_scope == new_scope:
        return

    # Only the destructive direction is blocked. A full run over a sample map is
    # a repair, not a regression, so it must stay allowed.
    if not full and old_scope == SCOPE_FULL:
        raise SystemExit(
            f"Refusing to overwrite a scope={old_scope} entity map with a scope={new_scope} run.\n"
            f"  {ENTITY_MAP_PATH.name} was built from {existing.get('records', '?')} records "
            f"and {existing.get('match_edges', '?')} match edges.\n"
            "  A sample run leaves every unscored record as a singleton that still looks "
            "complete, which would ship roughly 1,700 wrong master customers.\n"
            "  Use --full to refresh it, or pass --force if you really mean to replace it."
        )


def connected_components(
    record_ids: list[str], edges: pd.DataFrame
) -> dict[str, str]:
    """Union-find over match edges. No graph library needed for a forest this size.

    Entity ids are assigned from the lowest record_id in each component, so the
    same input always produces the same entity_id.
    """
    parent = {rid: rid for rid in record_ids}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            # Keep the lexicographically smaller root as the representative.
            low, high = sorted((root_a, root_b))
            parent[high] = low

    for left, right in zip(edges["record_id_l"], edges["record_id_r"]):
        union(left, right)

    groups: dict[str, list[str]] = {}
    for rid in record_ids:
        groups.setdefault(find(rid), []).append(rid)

    entity_ids = {
        rid: f"ent_{i:06d}"
        for i, root in enumerate(sorted(groups, key=lambda r: min(groups[r])), start=1)
        for rid in groups[root]
    }
    return entity_ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster matched pairs into entities.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Use the full-run predictions instead of the sample ones.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow a sample run to overwrite a full-run entity map.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Explicitly run on the smoke sample. This is the default.",
    )
    args = parser.parse_args()

    started = time.perf_counter()
    if not PROCESSED_DATA_PATH.exists():
        raise FileNotFoundError("Run python -m src.standardize first.")

    guard_against_scope_downgrade(full=args.full, force=args.force)

    records = pd.read_parquet(PROCESSED_DATA_PATH)[["record_id"]]
    preds = load_predictions(args.full)

    # Records the predictions could not have scored are not evidence of
    # "no duplicates here", so say so instead of reporting a clean result.
    modelled = set(preds["record_id_l"]) | set(preds["record_id_r"])
    unscored = len(records) - len(records[records["record_id"].isin(modelled)])
    if unscored and not args.full:
        print(
            f"WARNING: {unscored:,} of {len(records):,} records were never scored, so their "
            "singletons mean 'unexamined', not 'unique'. Use --full for a real answer."
        )

    # Cluster on the three-way decision, not on a raw probability, so REVIEW and
    # NON_MATCH stay unmerged by construction: an uncertain pair must not quietly
    # become a merged customer. Fall back to the threshold for older artifacts.
    if "decision" in preds.columns:
        edges = preds[preds["decision"] == "MATCH"]
        n_review = int((preds["decision"] == "REVIEW").sum())
        print(
            f"Decisions: MATCH={len(edges):,} REVIEW={n_review:,} "
            f"NON_MATCH={int((preds['decision'] == 'NON_MATCH').sum()):,}"
        )
        print(
            "  REVIEW pairs are NOT merged. They are the human queue: "
            f"probability between {REVIEW_THRESHOLD:g} and {MATCH_THRESHOLD}."
        )
    else:
        edges = preds[preds["match_probability"] >= MATCH_THRESHOLD]
        print(
            f"WARNING: predictions have no 'decision' column (older artifact). "
            f"Falling back to threshold {MATCH_THRESHOLD}; re-run src.splink_model."
        )
    entity_ids = connected_components(records["record_id"].tolist(), edges)

    entity_map = records.copy()
    entity_map["entity_id"] = entity_map["record_id"].map(entity_ids)
    entity_map.to_parquet(ENTITY_MAP_PATH, index=False)

    sizes = entity_map.groupby("entity_id").size()
    summary = {
        "records": len(entity_map),
        "entities": len(sizes),
        "match_edges": len(edges),
        "review_pairs": int((preds["decision"] == "REVIEW").sum())
        if "decision" in preds.columns
        else 0,
        "records_merged": int(len(entity_map) - len(sizes)),
        "largest_entity": int(sizes.max()),
        "singleton_entities": int((sizes == 1).sum()),
        "unscored_records": unscored,
        "threshold": MATCH_THRESHOLD,
        "scope": scope_of(args.full),
        "runtime_seconds": round(time.perf_counter() - started, 2),
    }
    pd.DataFrame([summary]).to_csv(CLUSTER_SUMMARY_PATH, index=False)
    write_meta(ENTITY_MAP_PATH, artifact="entity_map", **summary)

    print(f"Records: {summary['records']:,}")
    print(f"Entities: {summary['entities']:,}")
    print(f"Match edges (p>={MATCH_THRESHOLD}): {summary['match_edges']:,}")
    print(f"Records merged away: {summary['records_merged']:,}")
    print(f"Largest entity: {summary['largest_entity']}")
    print(f"Single-record entities: {summary['singleton_entities']:,}")
    print(f"Cluster size distribution: {sizes.value_counts().sort_index().to_dict()}")
    print(f"Saved: {ENTITY_MAP_PATH}")
    print(f"Saved: {CLUSTER_SUMMARY_PATH}")


if __name__ == "__main__":
    main()
