"""Model/configuration versioning (PRD FR-13, MASTER_CONTEXT section 16).

MASTER_CONTEXT fixes the layout, so this module writes exactly that:

    models/v20260930_141500/
        model.json        trained Splink model
        metadata.json     what it was trained on
        thresholds.json   the decision policy it was evaluated under
        evaluation.json   what it scored, on what labels

MC section 15: "The model should NOT be retrained every time a new CSV
arrives." A model that is never persisted cannot be reused, cannot be compared
against a retrained version, and cannot be attributed when a reviewer's label is
recorded. Saving is therefore the first half of that requirement; reusing it
(FR-14) is the second and needs this to exist first.

MC section 16: "Never silently overwrite a previously validated production
model." Every run therefore gets its own directory, and `latest.json` is a
pointer, not a copy.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import (
    BENCHMARK_RULES,
    LAMBDA_RECALL_ASSUMPTION,
    M_ELSE_LEVEL_FLOOR,
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    PROJECT_ROOT,
    RANDOM_SEED,
    REVIEW_THRESHOLD,
)

MODELS_DIR = PROJECT_ROOT / "models"
LATEST_POINTER = MODELS_DIR / "latest.json"

# The four artifacts MASTER_CONTEXT section 16 names. A version directory
# missing any of them is not a reviewable model version.
REQUIRED_FILES = ("model.json", "metadata.json", "thresholds.json", "evaluation.json")


def version_id(created: datetime | None = None) -> str:
    return (created or datetime.now()).strftime("v%Y%m%d_%H%M%S")


def version_dir(vid: str) -> Path:
    return MODELS_DIR / vid


def save_version(
    linker,
    pred_df: pd.DataFrame,
    scope: str,
    runtime_seconds: float,
    extra_metadata: dict | None = None,
) -> Path:
    """Write one immutable model version and return its directory.

    A sample run is saved but never becomes the active model: `latest` is what
    inference, the dashboard and incremental scoring read, and a 10k sample
    version pointing at it would replace the full-scope model that 51,555
    records were resolved with.
    """
    created = datetime.now()
    vid = version_id(created)
    target = version_dir(vid)
    target.mkdir(parents=True, exist_ok=True)

    model_json = linker.misc.save_model_to_json()
    (target / "model.json").write_text(json.dumps(model_json, indent=2), encoding="utf-8")

    decisions = (
        pred_df["decision"].value_counts().to_dict()
        if "decision" in pred_df.columns
        else {}
    )
    total = len(pred_df)
    metadata = {
        "version": vid,
        "created_at": created.isoformat(timespec="seconds"),
        "scope": scope,
        "input_rows": extra_metadata.get("input_rows") if extra_metadata else None,
        "pairs_scored": total,
        "blocking_rules": [name for name, _ in BENCHMARK_RULES],
        "lambda_recall_assumption": LAMBDA_RECALL_ASSUMPTION,
        "m_else_level_floor": M_ELSE_LEVEL_FLOOR,
        "random_seed": RANDOM_SEED,
        "splink_version": extra_metadata.get("splink_version") if extra_metadata else None,
        "runtime_seconds": runtime_seconds,
        **(extra_metadata or {}),
    }
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # Thresholds live beside the model because a score without its decision policy
    # is not reproducible. Reviewing v1 under v2's thresholds would silently
    # change what MATCH means.
    thresholds = {
        "match_threshold": MATCH_THRESHOLD,
        "review_threshold": REVIEW_THRESHOLD,
        "policy": "P >= match -> MATCH; review <= P < match -> REVIEW; P < review -> NON_MATCH",
    }
    (target / "thresholds.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")

    evaluation = {
        "version": vid,
        "decisions": decisions,
        "decision_rates": {
            name: round(count / total, 6) if total else None
            for name, count in decisions.items()
        },
        "note": (
            "Counts produced by this run. Accuracy metrics are NOT here on purpose: "
            "they belong in outputs/threshold_evaluation_*.json and are only valid "
            "against the label source that produced them."
        ),
    }
    (target / "evaluation.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")

    if scope != "sample":
        LATEST_POINTER.write_text(
            json.dumps(
                {
                    "version": vid,
                    "path": str(target),
                    "created_at": created.isoformat(timespec="seconds"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return target


def load_model_json(path: Path | str) -> dict:
    """Read a saved model for inference without retraining (FR-14)."""
    path = Path(path)
    if path.is_dir():
        path = path / "model.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No model at {path}. Train one first: python -m src.splink_model --full"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def latest() -> Path | None:
    if not LATEST_POINTER.exists():
        return None
    pointer = json.loads(LATEST_POINTER.read_text(encoding="utf-8"))
    target = Path(pointer["path"])
    return target if target.exists() else None


def list_versions() -> list[dict]:
    if not MODELS_DIR.exists():
        return []
    out = []
    for path in sorted(MODELS_DIR.glob("v*")):
        if not path.is_dir():
            continue
        meta_file = path / "metadata.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        out.append(
            {
                "version": path.name,
                "created_at": meta.get("created_at"),
                "pairs_scored": meta.get("pairs_scored"),
                "scope": meta.get("scope"),
                "complete": all((path / f).exists() for f in REQUIRED_FILES),
            }
        )
    return out


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="List saved model versions.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    args = parser.parse_args()

    versions = list_versions()
    if args.json:
        print(json.dumps(versions, indent=2))
        return
    if not versions:
        print(f"No model versions yet in {MODELS_DIR}")
        print("Train one: python -m src.splink_model --full")
        return
    frame = pd.DataFrame(versions)
    frame["latest"] = frame["version"] == (
        latest().name if latest() else None
    )
    print(frame.to_string(index=False))
    print(f"\nTotal: {len(frame)} version(s) in {MODELS_DIR}")


if __name__ == "__main__":
    main()
