from __future__ import annotations

import re
import time

import pandas as pd

from .config import (
    ENTITY_MAP_PATH,
    MASTER_PATH,
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    SCOPE_FULL,
    read_meta,
    write_meta,
)

MASTER_SUMMARY_PATH = OUTPUT_DIR / "master_summary.csv"

# device_ids_std holds a list per row, so it cannot take part in a value-mode
# pick. It stays available in the standardized parquet for audit.
MASTER_FIELDS = [
    "first_name_std",
    "last_name_std",
    "email_std",
    "phone_std",
    "dob_std",
    "address_std",
    "city_std",
    "state_std",
    "country_std",
]
LINEAGE_FIELDS = ["record_id", "customer_id", "source"]


def corruption_score(value: str) -> int:
    """How corrupted a normalized value looks.

    Tie-breaking alphabetically is arbitrary and, on this data, systematically
    wrong: a pair like ("burton", "bbuurrton") always resolves to the typo
    because "b" < "u". Profiling measured 10,666 records with a repeated
    adjacent character and 48,473 with mixed case, so penalising those two
    patterns is traceable to a measured finding rather than a guess.
    """
    text = str(value)
    repeats = len(re.findall(r"(.)\1", text))
    digits = len(re.findall(r"\d", text))
    symbols = len(re.findall(r"[^a-z\s'’-]", text))
    return repeats + digits + symbols


def pick_master_values(frame: pd.DataFrame) -> pd.DataFrame:
    """Best supported, least corrupted standardized value per entity and field.

    Order: most records agree, then least corrupted, then alphabetical. Every
    level is deterministic so the same input always yields the same master
    record.
    """
    long = frame.melt(
        id_vars=["entity_id"],
        value_vars=MASTER_FIELDS,
        var_name="field",
        value_name="value",
    ).dropna(subset=["value"])

    counts = long.groupby(["entity_id", "field", "value"]).size().reset_index(name="n")
    counts["corruption"] = counts["value"].map(corruption_score)
    # n desc, corruption asc, value asc.
    counts = counts.sort_values(
        ["entity_id", "field", "n", "corruption", "value"],
        ascending=[True, True, False, True, True],
    )
    best = counts.drop_duplicates(["entity_id", "field"])[["entity_id", "field", "value"]]

    wide = best.pivot(index="entity_id", columns="field", values="value").reset_index()
    wide.columns = ["entity_id", *[f"master_{c}" for c in wide.columns[1:]]]
    return wide


def build_lineage(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = frame.groupby("entity_id")
    # source has 1,281 nulls in the current batches (measured 2026-10-01), and an
    # entity can mix a null with a real value — sorted({None, 'referral'}) raises
    # TypeError. Nulls are dropped from the list: an entity with no source at all
    # yields [] rather than [None].
    return pd.DataFrame(
        {
            "record_count": grouped["record_id"].nunique(),
            "record_ids": grouped["record_id"].apply(lambda s: sorted(s.tolist())),
            "customer_ids": grouped["customer_id"].apply(
                lambda s: sorted(set(s.dropna().tolist()))
            ),
            "sources": grouped["source"].apply(
                lambda s: sorted(set(s.dropna().tolist()))
            ),
        }
    ).reset_index()


def main() -> None:
    started = time.perf_counter()

    if not PROCESSED_DATA_PATH.exists():
        raise FileNotFoundError("Run python -m src.standardize first.")
    if not ENTITY_MAP_PATH.exists():
        raise FileNotFoundError("Run python -m src.clustering --full first.")

    records = pd.read_parquet(PROCESSED_DATA_PATH)
    entity_map = pd.read_parquet(ENTITY_MAP_PATH)
    frame = records.merge(entity_map[["record_id", "entity_id"]], on="record_id", how="inner")

    if len(frame) != len(records):
        raise ValueError(
            f"entity_map covers {len(frame):,} of {len(records):,} records; rebuild clustering"
        )

    # A sample-scope clustering covers every record_id too, so the length check
    # above cannot catch it. This is the last point where a wrong scope would
    # turn into a wrong master customer file.
    meta = read_meta(ENTITY_MAP_PATH)
    if meta and meta.get("scope") != SCOPE_FULL:
        raise SystemExit(
            f"{ENTITY_MAP_PATH.name} was built with scope={meta.get('scope')} "
            f"({meta.get('unscored_records', '?')} records never scored).\n"
            "  Building master records from it would emit those as distinct customers.\n"
            f"  Run: python -m src.clustering --full"
        )

    missing = [c for c in MASTER_FIELDS + LINEAGE_FIELDS if c not in frame.columns]
    if missing:
        raise ValueError(f"standardized data is missing columns: {missing}")

    master = build_lineage(frame).merge(pick_master_values(frame), on="entity_id", how="left")

    # Provenance: which fields disagreed inside the entity, so a reviewer can see
    # where the master value was a judgement call.
    conflicts = (
        frame.melt(
            id_vars=["entity_id"],
            value_vars=MASTER_FIELDS,
            var_name="field",
            value_name="value",
        )
        .dropna(subset=["value"])
        .groupby(["entity_id", "field"])["value"]
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

    master.to_parquet(MASTER_PATH, index=False)
    write_meta(
        MASTER_PATH,
        artifact="master_customers",
        scope=SCOPE_FULL,
        entities=len(master),
        records=int(master["record_count"].sum()),
        source_entity_map_scope=meta.get("scope"),
        match_threshold=MATCH_THRESHOLD,
    )

    summary = pd.DataFrame(
        [
            {
                "entities": len(master),
                "records": int(master["record_count"].sum()),
                "multi_record_entities": int((master["record_count"] > 1).sum()),
                "largest_entity": int(master["record_count"].max()),
                "entities_with_conflicts": int((master["conflicted_fields"].apply(len) > 0).sum()),
                "mean_customer_ids_per_entity": round(
                    master["customer_ids"].apply(len).mean(), 4
                ),
                "runtime_seconds": round(time.perf_counter() - started, 2),
            }
        ]
    )
    summary.to_csv(MASTER_SUMMARY_PATH, index=False)

    print(summary.to_string(index=False))
    print(f"Saved: {MASTER_PATH}")
    print(f"Saved: {MASTER_SUMMARY_PATH}")


if __name__ == "__main__":
    main()
