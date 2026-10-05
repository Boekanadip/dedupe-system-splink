from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .config import OUTPUT_DIR, predictions_path, read_meta
from .labels import load_labels

THRESHOLDS = [0.5, 0.9, 0.95, 0.99, 0.995, 0.999, 0.9995, 0.9999]
OUTPUT_DIR = Path(OUTPUT_DIR)
# Named by label source so a gold evaluation cannot overwrite a silver one and
# look like the same measurement. Reading threshold_evaluation_silver.json for a
# gold run is how a silver artifact gets quoted as a gold result.
OUTPUT_BY_SOURCE = {
    "gold": OUTPUT_DIR / "threshold_evaluation_gold.json",
    "silver": OUTPUT_DIR / "threshold_evaluation_silver.json",
}


def evaluate_at(pairs: pd.DataFrame, label_col: str, prob_col: str, thresh: float) -> dict:
    tp = int(((pairs[label_col] == 1) & (pairs[prob_col] >= thresh)).sum())
    fp = int(((pairs[label_col] == 0) & (pairs[prob_col] >= thresh)).sum())
    fn = int(((pairs[label_col] == 1) & (pairs[prob_col] < thresh)).sum())
    tn = int(((pairs[label_col] == 0) & (pairs[prob_col] < thresh)).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "threshold": thresh,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Threshold evaluation on labelled pairs.")
    parser.add_argument(
        "--source",
        choices=["auto", "silver", "gold"],
        default="auto",
        help="Which label set to evaluate against.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Use full-run predictions (default: 10k sample).",
    )
    args = parser.parse_args()

    preds_path = predictions_path(full=args.full)
    if not preds_path.exists():
        raise FileNotFoundError(
            f"{preds_path.name} not found. Run: python -m src.splink_model"
            + (" --full" if args.full else "")
        )
    preds = pd.read_parquet(preds_path)

    if not args.full:
        # Same labels the evaluation will use, otherwise the coverage check
        # below could pass on a set that is never scored.
        labels, _ = load_labels(args.source)
        if labels is not None:
            modelled = set(preds["record_id_l"]) | set(preds["record_id_r"])
            in_scope = labels[
                labels["record_id_l"].isin(modelled) & labels["record_id_r"].isin(modelled)
            ]
            if len(in_scope) < len(labels):
                raise SystemExit(
                    f"Sample predictions cover only {len(in_scope):,} of {len(labels):,} "
                    "labelled pairs. Evaluation would report 100% recall on the covered "
                    "subset while ignoring the rest. Use --full."
                )

    # "auto" keeps the old gold-first preference. Pinning a source is what makes
    # --source silver reachable now that gold_labels.csv exists.
    labels, src = load_labels(args.source)
    if labels is None:
        raise SystemExit(
            f"No {args.source if args.source != 'auto' else 'gold or silver'} labels found. "
            + (
                "Run: python -m src.labels --promote"
                if args.source in ("gold", "auto")
                else "Run: python -m src.labels --silver-only"
            )
        )

    print(f"Evaluating {len(labels):,} labelled pairs against predictions (source: {src}).")
    positives = int(labels["is_positive"].sum())
    negatives = len(labels) - positives
    if src == "silver":
        print("WARNING: SILVER labels are deterministic high-precision / high-recall heuristics.")
        print("  Positives = exact phone+dob matches (easy). Negatives = conflicting dob+name (easy).")
        print("  Metrics will be OPTIMISTICALLY biased. Do not use for production threshold.")
    else:
        print("GOLD labels: reviewed by a human.")
        if negatives == 0 or positives == 0:
            # Without both classes present, one of the two metrics is 1.0 by
            # construction and cannot be quoted as an achievement.
            print(
                f"  CAVEAT: {positives:,} positives / {negatives:,} negatives. A set with a "
                "single class cannot measure both precision and recall: one of them is 1.0 "
                f"by construction. Report this as 'n={len(labels):,} reviewed pairs', "
                "not as recall/precision."
            )
        print(
            "  CAVEAT: this gold set is stratified by the model's own behaviour, not a random "
            "sample of the population. Rates from it do not extrapolate to all pairs."
        )

    merged = preds.merge(
        labels[["record_id_l", "record_id_r", "is_positive"]],
        on=["record_id_l", "record_id_r"],
        how="inner",
    )
    merged["label"] = merged["is_positive"].astype(int)

    results = []
    for thresh in THRESHOLDS:
        m = evaluate_at(merged, "label", "match_probability", thresh)
        results.append(m)
        print(
            f"thresh={thresh:.4f} tp={m['tp']:4d} fp={m['fp']:4d} fn={m['fn']:4d} "
            f"tn={m['tn']:4d} prec={m['precision']:.4f} rec={m['recall']:.4f} f1={m['f1']:.4f}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_BY_SOURCE[src]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "label_source": src,
                "positives": positives,
                "negatives": negatives,
                "warnings": (
                    "SILVER labels — optimistic bias"
                    if src == "silver"
                    else "GOLD labels — reviewed by a human, but stratified, not a random sample"
                ),
                "results": results,
            },
            f,
            indent=2,
        )
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()