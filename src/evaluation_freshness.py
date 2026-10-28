
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import LABELS_DIR, PROCESSED_DATA_PATH, predictions_path, read_meta
from .registry import sha256_of

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
GOLD_PATH = LABELS_DIR / "gold_labels.csv"
FRESHNESS_FIELDS = (
    "gold_sha256",
    "processed_data_sha256",
    "prediction_sha256",
    "model_inventory_sha256",
)


def model_inventory_sha256(blocking_rules: list | None = None) -> str:
    """Fingerprint the full-scope models included in the comparison report."""
    inventory = []
    for path in sorted(MODELS_DIR.glob("v*")):
        meta_path = path / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("scope") != "full":
            continue
        if blocking_rules is not None and meta.get("blocking_rules") != blocking_rules:
            continue

        model_path = path / "model.json"
        thresholds_path = path / "thresholds.json"
        inventory.append(
            {
                "version": path.name,
                "metadata_sha256": sha256_of(meta_path),
                "model_sha256": sha256_of(model_path) if model_path.exists() else None,
                "thresholds_sha256": (
                    sha256_of(thresholds_path) if thresholds_path.exists() else None
                ),
            }
        )
    payload = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def current_provenance() -> dict:
    """Hash the current input artifacts used by the comparable-score report."""
    pred_path = predictions_path(full=True)
    pred_meta = read_meta(pred_path)

    def artifact_hash(path: Path) -> str | None:
        return sha256_of(path) if path.exists() else None

    return {
        "gold_sha256": artifact_hash(GOLD_PATH),
        "processed_data_sha256": artifact_hash(PROCESSED_DATA_PATH),
        "prediction_sha256": artifact_hash(pred_path),
        "model_inventory_sha256": (
            model_inventory_sha256(pred_meta.get("blocking_rules"))
            if pred_path.exists()
            else None
        ),
    }


def compare_provenance(saved: dict, current: dict) -> tuple[list[str], list[str]]:
    """Return provenance fields missing from a report and fields that changed."""
    missing = [field for field in FRESHNESS_FIELDS if field not in saved]
    changed = [
        field
        for field in FRESHNESS_FIELDS
        if field in saved and saved[field] != current.get(field)
    ]
    return missing, changed
