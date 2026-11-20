"""Sinkronkan meta model antara entity_map dan splink_predictions."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from src.config import predictions_path, read_meta

OUTPUT = Path("outputs")


def main():
    emeta_path = OUTPUT / "entity_map.parquet.meta.json"
    pmeta_path = OUTPUT / "splink_predictions.parquet.meta.json"

    if not emeta_path.exists() or not pmeta_path.exists():
        print("File meta tidak ditemukan di outputs/")
        return

    emeta = json.loads(emeta_path.read_text())
    pmeta = json.loads(pmeta_path.read_text())

    issues = []
    if emeta.get("model_version") != pmeta.get("model_version"):
        issues.append(
            f"model_version mismatch: entity_map={emeta.get('model_version')}, "
            f"predictions={pmeta.get('model_version')}"
        )
    if emeta.get("threshold") != pmeta.get("threshold"):
        issues.append(
            f"threshold mismatch: entity_map={emeta.get('threshold')}, "
            f"predictions={pmeta.get('threshold')}"
        )

    if issues:
        print("! Issues found:")
        for i in issues:
            print(" -", i)
        # ekspor meta sinkronized (prioritas predictions karena lebih baru/Nov 2026)
        out = pmeta.copy()
        (OUTPUT / "meta_sync.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
        print("=> Dis ekspor ke outputs/meta_sync.json")
    else:
        print("✅ Meta sudah konsisten")


if __name__ == "__main__":
    main()