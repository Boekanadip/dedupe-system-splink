"""Pembuatan versi model/konfigurasi (PRD FR-13, bagian 16 MASTER_CONTEXT).

MASTER_CONTEXT menetapkan struktur berkas, sehingga modul ini menulis sesuai
struktur tersebut:

    models/v20260930_141500/
        model.json        model Splink yang telah dilatih
        metadata.json     data yang digunakan untuk melatihnya
        thresholds.json   kebijakan keputusan yang dievaluasi
        evaluation.json   hasil skor dan label yang digunakan

Bagian 15 MC: "Model TIDAK boleh dilatih ulang setiap kali CSV baru diterima."
Model yang tidak pernah disimpan tidak dapat digunakan kembali, dibandingkan
dengan versi hasil pelatihan ulang, atau dikaitkan dengan label peninjau yang
dicatat. Karena itu, penyimpanan memenuhi bagian pertama persyaratan tersebut;
penggunaan kembali (FR-14) adalah bagian kedua dan bergantung pada penyimpanan.

Bagian 16 MC: "Jangan pernah menimpa model produksi yang telah divalidasi tanpa
pemberitahuan." Karena itu, setiap proses mendapat direktorinya sendiri dan
`latest.json` berfungsi sebagai penunjuk, bukan salinan.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import (
    LAMBDA_RECALL_ASSUMPTION,
    M_ELSE_LEVEL_FLOOR,
    M_ELSE_LEVEL_FLOOR_BY_FIELD,
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    PROJECT_ROOT,
    RANDOM_SEED,
    REVIEW_THRESHOLD,
    atomic_write_parquet,
    atomic_write_json,
    load_benchmark_rules,
)

MODELS_DIR = PROJECT_ROOT / "models"
LATEST_POINTER = MODELS_DIR / "latest.json"

# Empat artefak yang disebut pada bagian 16 MASTER_CONTEXT. Direktori versi yang
# tidak memiliki salah satunya belum layak ditinjau sebagai versi model.
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
    """Simpan satu versi model yang tidak dapat diubah dan kembalikan direktorinya.

    Proses sampel disimpan, tetapi tidak pernah menjadi model aktif: inferensi,
    dasbor, dan pemberian skor inkremental membaca `latest`. Jika diarahkan ke
    versi sampel 10 ribu baris, model cakupan penuh yang digunakan untuk
    menyelesaikan 51.555 catatan akan tergantikan.
    """
    created = datetime.now()
    vid = version_id(created)
    target = version_dir(vid)
    target.mkdir(parents=True, exist_ok=True)

    model_json = linker.misc.save_model_to_json()
    atomic_write_json(model_json, target / "model.json")

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
        "blocking_rules": [name for name, _ in load_benchmark_rules()],
        "lambda_recall_assumption": LAMBDA_RECALL_ASSUMPTION,
        "m_else_level_floor": M_ELSE_LEVEL_FLOOR,
        "m_else_level_floor_by_field": M_ELSE_LEVEL_FLOOR_BY_FIELD,
        "random_seed": RANDOM_SEED,
        "splink_version": extra_metadata.get("splink_version") if extra_metadata else None,
        "runtime_seconds": runtime_seconds,
        **(extra_metadata or {}),
    }
    atomic_write_json(metadata, target / "metadata.json")

    # Ambang disimpan bersama model karena skor tanpa kebijakan keputusan tidak
    # dapat direproduksi. Meninjau v1 dengan ambang v2 akan diam-diam mengubah
    # arti MATCH.
    thresholds = {
        "match_threshold": MATCH_THRESHOLD,
        "review_threshold": REVIEW_THRESHOLD,
        "policy": "P >= match -> MATCH; review <= P < match -> REVIEW; P < review -> NON_MATCH",
    }
    atomic_write_json(thresholds, target / "thresholds.json")

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
    atomic_write_json(evaluation, target / "evaluation.json")

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
    """Muat model tersimpan untuk inferensi tanpa melatih ulang (FR-14)."""
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
