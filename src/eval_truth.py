"""Score the linkage against device_id, a channel the pipeline never uses.

WHY THIS EXISTS
Silver labels are defined as `phone_std + dob_std` agreement, and those exact
fields are blocking keys, so coverage against silver is 100% by construction and
F1 against silver is an artifact. It cannot answer "how accurate is it?".

`device_id(s)` is a different channel: it is not a blocking key and not a
comparison anywhere in the model, so agreement with it is not built into the
pipeline. MEASURED on this file: 48,200 distinct device ids over 48,200
customer_id groups, and no group carries two different device ids. So device_id
is 1:1 with the source identity. That makes it the answer key, NOT independent
evidence:

  - What it proves: blocking + Splink + clustering reproduce the source grouping
    without ever reading customer_id or device_id.
  - What it cannot prove: anything about fuzzy duplicates, real-world recall, or
    a client's data. One fact counted four ways is not four confirmations.

Recall against a channel that cannot disagree is therefore an UPPER bound, and
is only meaningful when it is below 1.0. See src/stress_test.py for the run
where corruption makes it informative.

This module also owns the pair SQL so the benchmark and the evaluation cannot
drift apart: they must score the same pairs to be comparable.
"""

from __future__ import annotations

import argparse
import json

import duckdb
import pandas as pd

from .config import BENCHMARK_RULES, MATCH_THRESHOLD, OUTPUT_DIR, PROCESSED_DATA_PATH, predictions_path

EVALUATION_PATH = OUTPUT_DIR / "evaluation_device_truth.json"

TRUTH_SOURCE = "device_ids_std"


def pairs_sql(cols: list[str]) -> str:
    condition = "\n            AND ".join(f'l."{c}" = r."{c}"' for c in cols)
    return f"""
        SELECT l."record_id" AS record_id_l, r."record_id" AS record_id_r
        FROM src AS l
        INNER JOIN src AS r
            ON {condition}
        WHERE l."record_id" < r."record_id"
    """


def device_truth_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """Pairs of records that share a device id.

    Records with no device id cannot be expressed as a pair, so they are out of
    scope by construction. That is a property of this channel, not a model limit.
    """
    if "device_ids_std" not in df.columns:
        return pd.DataFrame(columns=["record_id_l", "record_id_r"])

    ids = df[["record_id", "device_ids_std"]].explode("device_ids_std").dropna(subset=["device_ids_std"])
    ids = ids[ids["device_ids_std"].astype(str).str.len() > 0]
    pairs = ids.merge(ids, on="device_ids_std", suffixes=("_l", "_r"))
    pairs = pairs[pairs["record_id_l"] < pairs["record_id_r"]]
    return pairs[["record_id_l", "record_id_r"]].drop_duplicates().reset_index(drop=True)


def match_edges(preds: pd.DataFrame, threshold: float = MATCH_THRESHOLD) -> pd.DataFrame:
    return preds[preds["match_probability"] >= threshold][["record_id_l", "record_id_r"]]


def records_with_device(df: pd.DataFrame) -> set[str]:
    """record_ids that carry at least one non-empty device id."""
    if "device_ids_std" not in df.columns:
        return set()
    ids = df[["record_id", "device_ids_std"]].explode("device_ids_std").dropna(subset=["device_ids_std"])
    ids = ids[ids["device_ids_std"].astype(str).str.len() > 0]
    return set(ids["record_id"])


def score(
    truth: pd.DataFrame,
    edges: pd.DataFrame,
    threshold: float,
    device_records: set[str] | None = None,
) -> dict:
    """Score match edges against the device-truth pairs.

    A MATCH edge that is not a truth pair is only a FALSE MERGE when BOTH records
    carry a device id. Records without one (batch_0005 arrived without
    device_id(s)) cannot appear in the truth channel at all — calling those edges
    "false merges" is a measurement mistake, not a model failure. Both numbers are
    returned separately.
    """
    found = truth.merge(edges, on=["record_id_l", "record_id_r"], how="inner")
    extra = edges.merge(truth, on=["record_id_l", "record_id_r"], how="left", indicator=True)
    extra = extra[extra["_merge"] == "left_only"]
    if device_records is None:
        unverifiable = 0
        false_merges = len(extra)
    else:
        both = extra["record_id_l"].isin(device_records) & extra["record_id_r"].isin(device_records)
        unverifiable = int((~both).sum())
        false_merges = int(both.sum())
    return {
        "threshold": threshold,
        "truth_pairs": len(truth),
        "matched_truth_pairs": len(found),
        "missed_truth_pairs": len(truth) - len(found),
        "match_edges": len(edges),
        "false_merges": false_merges,
        "unverifiable_edges": unverifiable,
        "recall": round(len(found) / len(truth), 4) if len(truth) else None,
        "precision": round(len(found) / len(edges), 4) if len(edges) else None,
    }


def rule_coverage(df: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Per-rule recall against the device truth. Not tautological: no rule blocks
    on device_id, so a rule cannot reach its own denominator by construction."""
    con = duckdb.connect()
    con.register("src", df)
    rows = []
    for name, cols in BENCHMARK_RULES:
        pairs = con.execute(pairs_sql(cols)).fetchdf()
        con.register("pairs_temp", pairs)
        kept = con.execute(
            """
            SELECT COUNT(*) FROM truth t
            WHERE EXISTS (
                SELECT 1 FROM pairs_temp p
                WHERE p.record_id_l = t.record_id_l AND p.record_id_r = t.record_id_r
            )
            """
        ).fetchone()[0]
        con.unregister("pairs_temp")
        rows.append(
            {
                "rule": name,
                "key_columns": "+".join(cols),
                "candidate_pairs": len(pairs),
                "device_truth_covered": kept,
                "device_truth_coverage_pct": round(100.0 * kept / len(truth), 3) if len(truth) else None,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score match edges against device_id (channel unused by the model)."
    )
    parser.add_argument("--sample", action="store_true", help="Use sample predictions (default).")
    parser.add_argument("--full", action="store_true", help="Use full-run predictions.")
    args = parser.parse_args()

    df = pd.read_parquet(PROCESSED_DATA_PATH)
    preds_path = predictions_path(full=args.full)
    if not preds_path.exists():
        raise FileNotFoundError(
            f"{preds_path.name} not found. Run: python -m src.splink_model"
            + (" --full" if args.full else "")
        )
    preds = pd.read_parquet(preds_path)[["record_id_l", "record_id_r", "match_probability"]]

    truth = device_truth_pairs(df)
    if truth.empty:
        # Not an error: device_id is an optional channel that does not exist on
        # every dataset. Say so rather than reporting 0 recall.
        print("No device_id column (or no shared device ids) in this dataset.")
        print(
            "  device-truth evaluation is skipped. Recall and precision are then "
            "UNMEASURED until a reviewed gold sample exists — they are not zero, "
            "and they are not 1.0. Use: python -m src.review_sample --band match"
        )
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        EVALUATION_PATH.write_text(
            json.dumps(
                {
                    "truth_source": TRUTH_SOURCE,
                    "status": "unavailable",
                    "reason": "device_ids_std missing or no shared device ids",
                    "predictions": preds_path.name,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Saved: {EVALUATION_PATH}")
        return

    edges = match_edges(preds, MATCH_THRESHOLD)
    dev_recs = records_with_device(df)
    overall = score(truth, edges, MATCH_THRESHOLD, dev_recs)
    per_rule = rule_coverage(df, truth)

    print(f"Truth channel : {TRUTH_SOURCE} (not a blocking key, not a comparison)")
    print(f"Truth pairs   : {overall['truth_pairs']:,}")
    print(f"Match edges   : {overall['match_edges']:,} (p >= {MATCH_THRESHOLD})")
    print(f"Matched       : {overall['matched_truth_pairs']:,}")
    print(f"Missed        : {overall['missed_truth_pairs']:,}")
    print(f"False merges  : {overall['false_merges']:,} (both sides have device data)")
    print(f"Unverifiable  : {overall['unverifiable_edges']:,} (at least one side lacks device data)")
    print(
        f"Recall {overall['recall']} / Precision {overall['precision']} - measured against a "
        "channel that is 1:1 with customer_id on this file, so it is an upper bound, not proof "
        "of real-world accuracy."
    )
    print("\nPer-rule device-truth coverage:")
    print(per_rule.to_string(index=False))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    per_rule.to_csv(OUTPUT_DIR / "device_truth_rule_coverage.csv", index=False)

    payload = {
        "truth_source": TRUTH_SOURCE,
        "truth_source_caveat": (
            "1:1 with customer_id on this dataset: this is the answer key, not independent "
            "evidence. Agreement proves the pipeline reproduces the source grouping; it "
            "proves nothing about fuzzy duplicates or another dataset."
        ),
        "predictions": preds_path.name,
        "scope": "full" if args.full else "sample",
        "overall": overall,
        "per_rule": per_rule.to_dict(orient="records"),
    }
    EVALUATION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved: {EVALUATION_PATH}")
    print(f"Saved: {OUTPUT_DIR / 'device_truth_rule_coverage.csv'}")


if __name__ == "__main__":
    main()