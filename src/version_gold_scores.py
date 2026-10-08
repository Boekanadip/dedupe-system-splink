from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import model_lifecycle, splink_model
from .config import (
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    REVIEW_THRESHOLD,
    RANDOM_SEED,
    predictions_path,
    read_meta,
)
from .label_audit import audit as audit_gold_against_device
from .labels import GOLD_PATH, load_labels
from .registry import sha256_of

REPORT_PATH = OUTPUT_DIR / "version_gold_scores.json"
COMMON_THRESHOLDS = (0.5, 0.9)


def _metrics(frame: pd.DataFrame, threshold: float) -> dict:
    pred = frame["match_probability"] >= threshold
    y = frame["is_positive"]
    tp = int((y & pred).sum())
    fp = int((~y & pred).sum())
    fn = int((y & ~pred).sum())
    tn = int((~y & ~pred).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": float(threshold),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _version_thresholds(version_dir: Path) -> tuple[float, float]:
    path = version_dir / "thresholds.json"
    if not path.exists():
        return MATCH_THRESHOLD, REVIEW_THRESHOLD
    data = json.loads(path.read_text(encoding="utf-8"))
    return float(data.get("match_threshold", MATCH_THRESHOLD)), float(
        data.get("review_threshold", REVIEW_THRESHOLD)
    )


def build() -> dict:
    labels, source = load_labels("gold")
    if labels is None:
        raise SystemExit("No gold labels. Promote reviewed pairs first: python -m src.labels --promote")

    pred_path = predictions_path(full=True)
    pred_meta = read_meta(pred_path)
    if pred_meta.get("scope") != "full":
        raise SystemExit("Full-scope predictions are required for a comparable baseline")

    records = pd.read_parquet(PROCESSED_DATA_PATH)
    if not records["record_id"].is_unique:
        raise ValueError("record_id must be unique")
    if labels.duplicated(["record_id_l", "record_id_r"]).any():
        raise ValueError("Gold contains conflicting or duplicate pair labels")
    gold_sha256 = sha256_of(GOLD_PATH)
    processed_sha256 = sha256_of(PROCESSED_DATA_PATH)
    prediction_sha256 = sha256_of(pred_path)

    disputed = audit_gold_against_device()
    disputed = disputed.loc[disputed["verdict"] == "contradicted", ["record_id_l", "record_id_r"]]
    disputed = disputed.assign(is_disputed=True)
    labels = labels.merge(disputed, on=["record_id_l", "record_id_r"], how="left")
    labels["is_disputed"] = labels["is_disputed"].eq(True)

    versions: list[dict] = []
    common_pairs: set[tuple[str, str]] | None = None
    common_candidates: int | None = None
    for path in sorted(model_lifecycle.MODELS_DIR.glob("v*")):
        meta_path = path / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("scope") != "full":
            continue
        if meta.get("blocking_rules") != pred_meta.get("blocking_rules"):
            continue

        saved = model_lifecycle.load_model_json(path)
        match_threshold, review_threshold = _version_thresholds(path)
        scored, _linker = splink_model.train_and_predict(records, model=saved, verbose=False)
        merged = labels.merge(
            scored[["record_id_l", "record_id_r", "match_probability"]],
            on=["record_id_l", "record_id_r"],
            how="inner",
        )
        pair_keys = set(merged[["record_id_l", "record_id_r"]].itertuples(index=False, name=None))
        if len(pair_keys) != len(merged):
            raise ValueError(f"{path.name} produced duplicate reviewed pairs")
        if common_pairs is None:
            common_pairs = pair_keys
            common_candidates = len(scored)
        elif pair_keys != common_pairs or len(scored) != common_candidates:
            raise ValueError(f"{path.name} has different candidates; versions cannot be compared")
        unscored = int(len(labels) - len(merged))

        entry = {
            "version": path.name,
            "model_sha256": sha256_of(path / "model.json"),
            "created_at": meta.get("created_at"),
            "trained_on_rows": meta.get("input_rows"),
            "splink_version": meta.get("splink_version"),
            "lambda_recall_assumption": meta.get("lambda_recall_assumption"),
            "m_else_level_floor": meta.get("m_else_level_floor"),
            "own_match_threshold": match_threshold,
            "own_review_threshold": review_threshold,
            "scored_gold_pairs": len(merged),
            "unscored_gold_pairs": unscored,
            "positive_pairs": int(merged["is_positive"].sum()),
            "disputed_pairs": int(merged["is_disputed"].sum()),
        }
        for tag, subset in (
            ("clean", merged[~merged["is_disputed"]]),
            ("including_disputed", merged),
        ):
            entry[tag] = {
                f"at_{t}": _metrics(subset, t)
                for t in (match_threshold, *COMMON_THRESHOLDS)
            }
        versions.append(entry)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": (
            "Every full-scope saved model re-scores the SAME standardized records "
            "with its frozen parameters; no retraining and no writes to models/ "
            "or outputs/. Gold pairs are joined on identical pair keys, so each "
            "version is judged on the same reviewed pairs. Every version also "
            "produces the same candidate pairs, so the comparison is like for "
            "like."
        ),
        "provenance": {
            "gold_sha256": gold_sha256,
            "gold_source": source,
            "gold_pairs": len(labels),
            "gold_positive_pairs": int(labels["is_positive"].sum()),
            "gold_disputed_pairs": int(labels["is_disputed"].sum()),
            "processed_data_sha256": processed_sha256,
            "prediction_sha256": prediction_sha256,
            "random_seed": RANDOM_SEED,
        },
        "limitation": (
            "Gold was sampled from earlier model candidates, not randomly from "
            "all pairs, and has few positive pairs, so these numbers measure "
            "relative movement on the reviewed set — not population accuracy. "
            "Disputed gold matches (device channel contradicts the label) are "
            "reported separately in 'including_disputed'. A version with more "
            "positives correct is only 'better' if false positives do not rise."
        ),
        "versions": versions,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score every saved full-scope model on the same gold pairs"
    )
    parser.parse_args()
    report = build()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {
        "saved": str(REPORT_PATH),
        "versions_compared": len(report["versions"]),
        "gold_pairs": report["provenance"]["gold_pairs"],
        "gold_positives": report["provenance"]["gold_positive_pairs"],
        "gold_disputed": report["provenance"]["gold_disputed_pairs"],
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
