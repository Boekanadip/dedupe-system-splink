"""Persist human review as reusable feedback data (PRD FR-09, FR-15, DESIGN section 12).

DESIGN section 12 names the fields this must carry:

    pair_id, record_id_l, record_id_r, score, decision,
    human_label, reviewer, timestamp, model_version

Three of those are not recorded anywhere today. `timestamp` and `model_version`
are what make a label attributable: without them, a reviewer decision cannot be
traced to the model that produced the score, and MASTER_CONTEXT section 15
lists "large accumulation of reviewed cases" as a retraining trigger — which
requires knowing which model each case came from.

APPEND-ONLY, deliberately. data/labels/feedback.csv is the accumulating
feedback store described in MASTER_CONTEXT section 14. Promotion from a queue is
idempotent on (record_id_l, record_id_r, model_version): re-promoting the same
queue after adding a reviewer note updates that row instead of duplicating it,
because the reviewer's judgement should not be counted twice.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd

from . import model_lifecycle
from .config import LABELS_DIR, PREDICTIONS_FULL_PATH, PREDICTIONS_SAMPLE_PATH
from .labels import (
    FP_SAMPLE_PATH,
    GOLD_PATH,
    QUEUE_PATH,
    _read_review,
    normalise_label,
)

FEEDBACK_PATH = LABELS_DIR / "feedback.csv"

REVIEW_SOURCES = (QUEUE_PATH, FP_SAMPLE_PATH)

FEEDBACK_COLUMNS = [
    "pair_id",
    "record_id_l",
    "record_id_r",
    "score",
    "decision",
    "human_label",
    "reviewer",
    "timestamp",
    "model_version",
    "stratum",
]


def _pair_id(left: str, right: str) -> str:
    a, b = sorted((str(left), str(right)))
    return f"{a}__{b}"


def _model_version() -> str | None:
    """The model that produced the scores being reviewed."""
    latest = model_lifecycle.latest()
    return latest.name if latest else None


def _decisions_for() -> pd.DataFrame:
    """record_id pair -> (score, decision) from whichever prediction file exists."""
    empty = pd.DataFrame(columns=["pair_id", "match_probability", "decision"])
    for path in (PREDICTIONS_FULL_PATH, PREDICTIONS_SAMPLE_PATH):
        if not path.exists():
            continue
        available = set(pd.read_parquet(path).columns)
        wanted = [
            c
            for c in ("record_id_l", "record_id_r", "match_probability", "decision")
            if c in available
        ]
        preds = pd.read_parquet(path, columns=wanted)
        if "decision" not in preds.columns:
            preds["decision"] = None
        preds["pair_id"] = [
            _pair_id(a, b) for a, b in zip(preds.record_id_l, preds.record_id_r)
        ]
        return preds[["pair_id", "match_probability", "decision"]]
    return empty


def collect() -> pd.DataFrame:
    """Read every review source and emit the feedback rows they contribute.

    gold_labels.csv is a source, not just an output: it is the durable copy of a
    review once the queue that held it has been regenerated. Without it, feedback
    would empty out every time the pipeline rebuilt the queue.
    """
    sources = [*REVIEW_SOURCES, GOLD_PATH]
    reviewed = []
    for path in sources:
        if not path.exists():
            continue
        frame = _read_review(path)
        if "label" not in frame.columns:
            continue
        frame = frame.copy()
        # gold already stores the normalised vocabulary; the queues store raw.
        frame["human_label"] = frame["label"].map(normalise_label)
        frame = frame[frame["human_label"].notna()]
        if frame.empty:
            continue
        frame["source"] = path.name
        reviewed.append(frame)

    if not reviewed:
        return pd.DataFrame(columns=FEEDBACK_COLUMNS)

    labels = pd.concat(reviewed, ignore_index=True)
    labels = labels.drop_duplicates(subset=["record_id_l", "record_id_r"], keep="last")
    a = labels["record_id_l"].astype(str)
    b = labels["record_id_r"].astype(str)
    labels["record_id_l"] = [min(x, y) for x, y in zip(a, b)]
    labels["record_id_r"] = [max(x, y) for x, y in zip(a, b)]
    labels["pair_id"] = [
        _pair_id(x, y) for x, y in zip(labels.record_id_l, labels.record_id_r)
    ]

    # Scores and decisions always come from the predictions parquet, never from
    # the review file: Excel rewrote those columns to comma-decimal notation on
    # the way in, so the review file's copy is unreliable. The review file's own
    # match_probability column is dropped first so the merge cannot produce a
    # suffixed duplicate.
    labels = labels.drop(columns=["match_probability"], errors="ignore")
    scores = _decisions_for()
    labels = labels.merge(scores, on="pair_id", how="left")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    labels["score"] = labels["match_probability"]
    labels["timestamp"] = now
    if "reviewer" not in labels.columns:
        labels["reviewer"] = None
    labels["model_version"] = _model_version()

    return labels[FEEDBACK_COLUMNS].sort_values("pair_id").reset_index(drop=True)


def merge(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """Append new feedback; update rows that already exist for the same model.

    Key is (pair_id, model_version): the same pair reviewed under v1 and under v2
    are two different observations about two different models.
    """
    if existing.empty:
        return incoming
    if incoming.empty:
        return existing

    key = ["pair_id", "model_version"]
    # A reviewer's later judgement replaces the earlier one, so `incoming` last.
    merged = pd.concat([existing, incoming], ignore_index=True)
    merged = merged.drop_duplicates(subset=key, keep="last")
    return merged.sort_values(key).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persist reviewed pairs as reusable feedback (DESIGN section 12)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching feedback.csv.",
    )
    args = parser.parse_args()

    incoming = collect()
    if incoming.empty:
        print("No reviewed pairs found in the review queue or FP sample.")
        print("Fill a 'label' column first: python -m src.review_sample --band match")
        return

    existing = (
        pd.read_csv(FEEDBACK_PATH) if FEEDBACK_PATH.exists() else pd.DataFrame()
    )
    updated = merge(existing, incoming)

    print(f"Collected {len(incoming):,} reviewed pair(s) from the queue sources.")
    print(f"Feedback rows: {len(existing):,} -> {len(updated):,}")
    print(f"Label breakdown: {incoming['human_label'].value_counts().to_dict()}")
    version = _model_version()
    print(f"Attributed to model version: {version or 'UNKNOWN (no saved model)'}")

    if args.dry_run:
        print("\n--dry-run: feedback.csv not written.")
        return

    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    updated.to_csv(FEEDBACK_PATH, index=False)
    print(f"Saved: {FEEDBACK_PATH}")
    print(
        "This file is the accumulation MASTER_CONTEXT section 15 uses as a "
        "retraining trigger. It is append-only; do not hand-edit it."
    )


if __name__ == "__main__":
    main()
