from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from .config import (
    BENCHMARK_RULES,
    ENTITY_MAP_PATH,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    predictions_path,
    read_meta,
)
from .eval_truth import device_truth_pairs, pairs_sql
from .label_audit import audit as audit_gold_against_device
from .labels import GOLD_PATH, normalise_label
from .registry import sha256_of

REPORT_PATH = OUTPUT_DIR / "stage0_audit.json"
SAMPLE_PATH = OUTPUT_DIR / "stage0_outside_blocking_sample.csv"
DISPUTE_REVIEW_PATH = OUTPUT_DIR / "stage0_dispute_review.csv"
ALTERNATIVE_RULES = (
    ("first_name_city", ["first_name_std", "city_std"]),
    ("last_name_city", ["last_name_std", "city_std"]),
)


def pair_keys(frame: pd.DataFrame) -> pd.DataFrame:
    left = frame["record_id_l"].astype(str)
    right = frame["record_id_r"].astype(str)
    return pd.DataFrame({"record_id_l": left.where(left < right, right),
                         "record_id_r": right.where(left < right, left)})


def evaluate_reviewed_entities(entities: pd.DataFrame, labels: pd.DataFrame) -> dict:
    if not entities["record_id"].is_unique or entities["entity_id"].isna().any():
        raise ValueError("entity_map must contain one non-null entity_id per record_id")
    lookup = entities.set_index("record_id")["entity_id"]
    sizes = entities.groupby("entity_id").size()
    joined = labels.assign(
        entity_l=labels["record_id_l"].map(lookup),
        entity_r=labels["record_id_r"].map(lookup),
    )
    present = joined["entity_l"].notna() & joined["entity_r"].notna()
    checked = joined[present]
    positives = checked[checked["is_positive"]]
    negatives = checked[~checked["is_positive"]]
    split = positives[positives["entity_l"] != positives["entity_r"]]
    merged = negatives[negatives["entity_l"] == negatives["entity_r"]]
    implicated = merged["entity_l"].drop_duplicates()
    return {
        "reviewed_pairs": len(labels),
        "pairs_with_both_records_in_map": len(checked),
        "pairs_missing_entity_mapping": int((~present).sum()),
        "reviewed_positive_pairs": len(positives),
        "reviewed_positive_pairs_split": len(split),
        "reviewed_negative_pairs": len(negatives),
        "reviewed_negative_pairs_merged": len(merged),
        "entities_containing_reviewed_negative_pair": len(implicated),
        "records_in_implicated_entities": int(sizes.reindex(implicated).sum()) if len(implicated) else 0,
        "largest_implicated_entity_size": int(sizes.reindex(implicated).max()) if len(implicated) else 0,
        "caveat": "Observed violations on reviewed pairs only; implicated entity members are not all proven wrong. These are not population error rates.",
    }


def evaluate_device_reference_entities(
    entities: pd.DataFrame, records: pd.DataFrame, truth: pd.DataFrame
) -> dict:
    if "device_ids_std" not in records.columns:
        return {"status": "unavailable", "reason": "device_ids_std not present"}
    lookup = entities.set_index("record_id")["entity_id"]
    pairs = truth.assign(entity_l=truth["record_id_l"].map(lookup),
                         entity_r=truth["record_id_r"].map(lookup))
    if pairs[["entity_l", "entity_r"]].isna().any().any():
        raise ValueError("Some device reference pairs are missing from entity_map")
    ids = records[["record_id", "device_ids_std"]].explode("device_ids_std")
    ids = ids.dropna(subset=["device_ids_std"])
    ids = ids[ids["device_ids_std"].astype(str).str.len() > 0]
    per_entity = ids.assign(entity_id=ids["record_id"].map(lookup)).groupby("entity_id")[
        "device_ids_std"
    ].nunique()
    return {
        "status": "measured" if len(ids) else "unavailable",
        "reference_pairs": len(truth),
        "reference_pairs_split": int((pairs["entity_l"] != pairs["entity_r"]).sum()),
        "entities_with_multiple_device_ids": int((per_entity > 1).sum()),
        "records_without_device_reference": len(records) - ids["record_id"].nunique(),
        "caveat": "Device IDs reflect source identity, not adjudicated real-world entities; multiple devices per person and records without devices limit this diagnostic.",
    }


def attach_review_evidence(records: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    evidence = [
        col for col in ("first_name_std", "last_name_std", "email_std", "phone_std",
                        "dob_std", "address_std", "city_std") if col in records.columns
    ]
    result = pairs.copy()
    for side in ("l", "r"):
        values = records[["record_id", *evidence]].rename(
            columns={"record_id": f"record_id_{side}",
                     **{col: f"{col}_{side}" for col in evidence}}
        )
        result = result.merge(values, on=f"record_id_{side}", how="left", validate="many_to_one")
    return result


def dispute_review_pack(records: pd.DataFrame, audit: pd.DataFrame) -> pd.DataFrame:
    disputes = audit[audit["verdict"] == "contradicted"].rename(
        columns={"human_label": "current_gold_label",
                 "match_probability": "gold_snapshot_probability"}
    ).drop(columns="verdict")
    disputes = attach_review_evidence(records, disputes)
    disputes["adjudicated_label"] = ""
    disputes["review_status"] = "pending"
    disputes["reviewer"] = ""
    disputes["reviewed_at"] = ""
    disputes["reviewer_note"] = ""
    return disputes


def sample_outside_blocking(
    records: pd.DataFrame, scored: pd.DataFrame, gold: pd.DataFrame, per_rule: int
) -> pd.DataFrame:
    if per_rule < 1:
        raise ValueError("per_rule must be positive")
    con = duckdb.connect()
    con.register("src", records)
    con.register("scored", scored[["record_id_l", "record_id_r"]])
    con.register("gold", gold[["record_id_l", "record_id_r"]])
    samples = []
    try:
        for name, cols in ALTERNATIVE_RULES:
            candidates = con.execute(
                f"""
                SELECT p.record_id_l, p.record_id_r
                FROM ({pairs_sql(cols)}) AS p
                LEFT JOIN scored AS s USING (record_id_l, record_id_r)
                LEFT JOIN gold AS g USING (record_id_l, record_id_r)
                WHERE s.record_id_l IS NULL AND g.record_id_l IS NULL
                ORDER BY hash(p.record_id_l, p.record_id_r)
                LIMIT ?
                """,
                [per_rule],
            ).fetchdf()
            candidates["stratum"] = f"outside_blocking_{name}"
            samples.append(candidates)
    finally:
        con.close()
    sample = pd.concat(samples, ignore_index=True).drop_duplicates(
        ["record_id_l", "record_id_r"]
    )
    sample = attach_review_evidence(records, sample)
    sample["label"] = ""
    sample["review_status"] = "pending"
    sample["reviewer"] = ""
    sample["reviewer_note"] = ""
    return sample


def build(per_rule: int = 25) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    pred_path = predictions_path(full=True)
    pred_meta = read_meta(pred_path)
    entity_meta = read_meta(ENTITY_MAP_PATH)
    if pred_meta.get("scope") != "full" or entity_meta.get("scope") != "full":
        raise ValueError("Full-scope predictions and entity_map with provenance are required")
    if not GOLD_PATH.exists():
        raise FileNotFoundError(f"Missing reviewed labels: {GOLD_PATH}")
    records = pd.read_parquet(PROCESSED_DATA_PATH)
    entities = pd.read_parquet(ENTITY_MAP_PATH, columns=["record_id", "entity_id"])
    if len(records) != pred_meta.get("input_rows") or len(records) != len(entities):
        raise ValueError("Predictions, standardized records and entity_map differ in scope")
    preds = pd.read_parquet(pred_path, columns=["record_id_l", "record_id_r"])
    if len(preds) != pred_meta.get("pairs_scored") or preds.duplicated().any():
        raise ValueError("Prediction candidate count or unique pair keys do not match provenance")
    gold_raw = pd.read_csv(GOLD_PATH, sep=None, engine="python")
    if not {"record_id_l", "record_id_r", "label"}.issubset(gold_raw.columns):
        raise ValueError("gold_labels.csv requires pair IDs and label")
    gold = pair_keys(gold_raw)
    gold["is_positive"] = gold_raw["label"].map(normalise_label).eq("match").to_numpy()
    if gold_raw["label"].map(normalise_label).isna().any():
        raise ValueError("gold_labels.csv contains invalid labels")
    if gold.duplicated(["record_id_l", "record_id_r"]).any():
        raise ValueError("gold_labels.csv contains duplicate pair keys; adjudicate first")
    device_audit = audit_gold_against_device()
    conflicts = pair_keys(device_audit[device_audit["verdict"] == "contradicted"])
    safe = gold.merge(conflicts.assign(disputed=True), how="left", on=["record_id_l", "record_id_r"])
    safe = safe[safe["disputed"].isna()].drop(columns="disputed")
    scoped = gold.merge(preds.assign(scored=True), how="left", on=["record_id_l", "record_id_r"])
    truth = device_truth_pairs(records)
    covered = truth.merge(preds, how="inner", on=["record_id_l", "record_id_r"])
    sample = sample_outside_blocking(records, preds, gold, per_rule)
    disputes = dispute_review_pack(records, device_audit)
    gold_digest = sha256_of(GOLD_PATH)
    for pack in (sample, disputes):
        pack["model_version"] = pred_meta.get("model_version")
        pack["gold_sha256"] = gold_digest
    feedback_path = GOLD_PATH.with_name("feedback.csv")
    feedback_overlap = None
    feedback_rows = None
    feedback_only_matches = None
    if feedback_path.exists():
        feedback = pd.read_csv(feedback_path, usecols=["record_id_l", "record_id_r", "human_label"])
        feedback_rows = len(feedback)
        feedback_keys = pair_keys(feedback)
        feedback_keys["human_label"] = feedback["human_label"].to_numpy()
        overlap = feedback_keys.merge(gold[["record_id_l", "record_id_r"]],
                                      on=["record_id_l", "record_id_r"], how="left", indicator=True)
        feedback_overlap = int(overlap["_merge"].eq("both").sum())
        feedback_only_matches = int((overlap["_merge"].eq("left_only")
                                     & overlap["human_label"].eq("match")).sum())
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "predictions": str(pred_path),
            "predictions_sha256": sha256_of(pred_path),
            "model_version": pred_meta.get("model_version"),
            "entity_map": str(ENTITY_MAP_PATH),
            "entity_map_sha256": sha256_of(ENTITY_MAP_PATH),
            "standardized_sha256": sha256_of(PROCESSED_DATA_PATH),
            "gold_labels": str(GOLD_PATH),
            "gold_sha256": gold_digest,
            "blocking_rules": [name for name, _ in BENCHMARK_RULES],
            "input_records": len(records),
        },
        "labels": {
            "gold_pairs": len(gold),
            "gold_matches": int(gold["is_positive"].sum()),
            "gold_no_matches": int((~gold["is_positive"]).sum()),
            "gold_strata": (
                {str(k): int(v) for k, v in gold_raw["stratum"].fillna("unrecorded").value_counts().items()}
                if "stratum" in gold_raw else None
            ),
            "gold_device_reference_conflicts_pending_adjudication": len(conflicts),
            "feedback_rows": feedback_rows,
            "gold_pairs_also_in_feedback": feedback_overlap,
            "feedback_only_matches_unverified": feedback_only_matches,
            "dispute_review_path": str(DISPUTE_REVIEW_PATH),
            "dispute_review_promote_instructions": stage1_promote_command(),
            "caveat": "Gold was sampled from earlier model candidates; feedback may repeat gold. Feedback-only matches lack verified reviewer provenance. Device differences are a review flag, not automatic correction.",
        },
        "blocking": {
            "candidate_pairs": len(preds),
            "gold_positive_pairs": int(gold["is_positive"].sum()),
            "gold_positive_pairs_in_candidates": int((scoped["is_positive"] & scoped["scored"].eq(True)).sum()),
            "device_reference_pairs": len(truth),
            "device_reference_pairs_in_candidates": len(covered),
            "device_reference_pairs_outside_candidates": len(truth) - len(covered),
            "new_outside_blocking_review_pairs": len(sample),
            "outside_blocking_review_path": str(SAMPLE_PATH),
            "outside_blocking_review_promote_instructions": (
                "Promote manually: copy record_id_l, record_id_r and label (match/no_match) "
                "from this file into data/labels/gold_labels.csv. "
                "python -m src.labels --promote does not read stage 0 review packs."
            ),
            "outside_blocking_sample_rules": [name for name, _ in ALTERNATIVE_RULES],
            "real_world_recall": None,
            "caveat": "Gold pairs were chosen from candidates, and device IDs reflect source identity. The new sample is enriched by alternative keys, not representative; reviews can find misses but cannot estimate population recall without an independent sampling design.",
        },
        "entity": {
            "all_gold_exploratory": evaluate_reviewed_entities(entities, gold),
            "excluding_pending_device_conflicts": evaluate_reviewed_entities(entities, safe),
            "device_reference": evaluate_device_reference_entities(entities, records, truth),
            "pending_device_conflicts": len(conflicts),
            "open_membership_flags": None,
        },
        "business_costs": {
            "status": "awaiting_business_owner",
            "false_merge_cost_per_incident": None,
            "missed_duplicate_cost_per_incident": None,
            "review_cost_per_pair": None,
            "note": "Define currency, time horizon, and incident severity with the business owner before changing automatic decisions.",
        },
        "shadow_classifier": {
            "status": "not_assessed_by_stage0",
            "undisputed_gold_matches": int(safe["is_positive"].sum()),
            "planned_test_split": "Group by connected reviewed records so no record appears in both train and test; use a real ingestion-time holdout only if independently dated reviews exist.",
            "required_provenance": ["splink_model_version", "gold_sha256", "feature_schema_version", "train_test_record_groups"],
            "reason": "Nine undisputed gold matches are insufficient for meaningful entity-disjoint training and testing. The 97 feedback-only matches lack verified reviewer provenance and remain pending in the current precision review file. Adjudicate conflicts and obtain independently reviewed difficult positives; feedback collection timestamps are not review times.",
        },
    }
    flags_path = GOLD_PATH.with_name("membership_flags.csv")
    if flags_path.exists():
        flags = pd.read_csv(flags_path)
        report["entity"]["open_membership_flags"] = int(flags["status"].eq("open").sum())
    return report, sample, disputes


def save_review_pack(path: Path, frame: pd.DataFrame, label_column: str) -> bool:
    if path.exists():
        existing = pd.read_csv(path)
        protected = (label_column, "reviewer", "reviewer_note", "reviewed_at")
        filled = any(
            col in existing and existing[col].fillna("").astype(str).str.strip().ne("").any()
            for col in protected
        )
        filled = filled or ("review_status" in existing
                            and existing["review_status"].fillna("pending").ne("pending").any())
        if filled:
            keys = ["record_id_l", "record_id_r"]
            old_pairs = set(map(tuple, existing[keys].itertuples(index=False, name=None)))
            new_pairs = set(map(tuple, frame[keys].itertuples(index=False, name=None)))
            old_version = set(existing["model_version"]) if "model_version" in existing else set()
            old_gold = set(existing["gold_sha256"]) if "gold_sha256" in existing else set()
            if old_pairs != new_pairs or old_version != set(frame["model_version"]) or old_gold != set(frame["gold_sha256"]):
                raise ValueError(f"{path.name} contains reviews from a different snapshot; it was not overwritten")
            return False
    frame.to_csv(path, index=False)
    return True


def stage1_promote_command() -> str:
    """Explain how a completed stage 0 pack reaches gold_labels.csv.

    src.labels.promote_gold only reads the strata queue and the FP sample,
    so a stage 0 pack is not promoted by that command. Reviewers must
    promote the pair key and adjudicated label by hand.
    """
    return (
        "Promote manually: copy record_id_l, record_id_r and "
        "adjudicated_label (match/no_match) from this file into "
        "data/labels/gold_labels.csv. python -m src.labels --promote "
        "does not read stage 0 review packs."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit labels, blocking and reviewed entity errors without changing routing.")
    parser.add_argument("--per-rule", type=int, default=25)
    args = parser.parse_args()
    report, sample, disputes = build(args.per_rule)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sample_saved = save_review_pack(SAMPLE_PATH, sample, "label")
    disputes_saved = save_review_pack(DISPUTE_REVIEW_PATH, disputes, "adjudicated_label")
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(REPORT_PATH), "sample": str(SAMPLE_PATH),
                      "sample_written": sample_saved, "dispute_review": str(DISPUTE_REVIEW_PATH),
                      "dispute_review_written": disputes_saved,
                      "labels": report["labels"], "blocking": report["blocking"],
                      "entity": report["entity"]}, indent=2))


if __name__ == "__main__":
    main()
