"""Validasi dan rebuild master customer dari gold_labels.

Alur:

1. Promosi review_queue.csv ke gold_labels.csv (jika ada yang belum).
2. Validasi setiap pasangan di gold_labels ada di predictions dan label valid.
3. Terapkan label pada prediksi: python -m src.apply_gold --apply --recluster.
   - Re-run: clustering -> master_record -> evaluate.
4. Sinkronkan tabel ternormalisasi di database: python scripts/sync_resolution_outputs.py --apply.

Perintah:

    python scripts/gold_rebuild.py            # dry-run (cetak saja)
    python scripts/gold_rebuild.py --apply    # jalankan sepenuhnya
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.config import (
    ENTITY_MAP_PATH,
    LABELS_DIR,
    MASTER_PATH,
    PROCESSED_DATA_PATH,
    predictions_path,
    read_meta,
)
from src.labels import GOLD_PATH, load_labels
from src.model_lifecycle import latest

LABEL_COLUMNS = {"record_id_l", "record_id_r", "is_positive"}


def validate_gold(gold: pd.DataFrame, preds: pd.DataFrame) -> dict:
    """Validasi label tidak ada pasangan yang tidak terdeteksi."""

    if not LABEL_COLUMNS <= set(gold.columns):
        missing = sorted(LABEL_COLUMNS - set(gold.columns))
        raise ValueError(f"gold_labels.csv missing columns: {missing}")

    unknown_pairs = pd.merge(
        gold[["record_id_l", "record_id_r"]].drop_duplicates(),
        preds[["record_id_l", "record_id_r"]].drop_duplicates(),
        on=["record_id_l", "record_id_r"],
        how="left",
        indicator=True,
    )
    missing = unknown_pairs[unknown_pairs["_merge"] == "left_only"]
    if len(missing):
        print(
            f"Peringatan: {len(missing):,} pasangan di gold_labels.csv tidak ada di prediksi."
        )
        print(missing.head(10).to_string(index=False))

    bad_labels = gold[~gold["is_positive"].isin({True, False, 1, 0})]
    if len(bad_labels):
        print(f"Peringatan: {len(bad_labels):,} baris memiliki label tidak dikenal:")
        print(bad_labels.head(10).to_string(index=False))

    return {
        "gold_rows": len(gold),
        "matched_in_preds": len(gold) - len(missing),
        "missing_pairs": len(missing),
        "bad_labels": len(bad_labels),
    }


def enrich_gold_entities() -> dict:
    """Tambahkan entity_id_l / entity_id_r dari entity_map hasil rebuild."""

    gold = pd.read_csv(GOLD_PATH, sep=None, engine="python")
    entity_map = pd.read_parquet(ENTITY_MAP_PATH, columns=["record_id", "entity_id"])
    mapping = entity_map.set_index("record_id")["entity_id"]

    gold["entity_id_l"] = gold["record_id_l"].map(mapping)
    gold["entity_id_r"] = gold["record_id_r"].map(mapping)
    gold["same_entity"] = gold["entity_id_l"] == gold["entity_id_r"]

    unmapped = int(gold["entity_id_l"].isna().sum() + gold["entity_id_r"].isna().sum())
    if unmapped:
        print(f"Peringatan: {unmapped:,} kolom entity_id tidak terpetakan.")

    gold.to_csv(GOLD_PATH, index=False)
    return {
        "rows": len(gold),
        "unmapped": unmapped,
        "same_entity_true": int(gold["same_entity"].sum()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Jalankan build ulang.")
    args = parser.parse_args(argv)

    gold_loaded, source = load_labels()
    if gold_loaded is None or source != "gold":
        print("Belum ada gold_labels.csv. Buat melalui halaman Review dan selesaikan pemeriksaan.")
        return 1

    print(f"Sumber label: {source}")
    print(f"Baris gold: {len(gold_loaded):,}")

    preds_path = predictions_path(full=True)
    if not preds_path.exists():
        print(f"Prediksi tidak ditemukan: {preds_path}")
        return 1
    preds = pd.read_parquet(
        preds_path,
        columns=["record_id_l", "record_id_r", "match_probability", "decision"],
    )

    report = validate_gold(gold_loaded, preds)
    print(f"Pasangan cocok dengan prediksi: {report['matched_in_preds']:,}")
    print(f"Pasangan belum jadi kandidat: {report['missing_pairs']:,} (akan ditambahkan dari gold)")
    print(f"Label tidak valid: {report['bad_labels']:,}")
    if report["bad_labels"]:
        print("\nSaran: perbaiki gold_labels.csv sebelum rebuild.")

    if not args.apply:
        print("\nDry-run. Tambahkan --apply untuk menjalankan apply + recluster + sync database.")
        return 0

    print("\n== Apply gold labels ==")
    import subprocess
    cmd = [sys.executable, "-m", "src.apply_gold", "--apply"]
    print(f"  running: {' '.join(cmd[2:])}")
    result = subprocess.run(cmd, text=True, capture_output=True)
    tail = [ln for ln in (result.stdout or "").splitlines() if ln.strip()]
    print("\n".join(tail[-5:]))
    if result.returncode != 0:
        print(result.stderr)
        return result.returncode

    print("\n== Rebuild entity_map + master ==")
    for module, extra in (("clustering", ["--full"]), ("master_record", [])):
        cmd = [sys.executable, "-m", f"src.{module}", *extra]
        print(f"  running: {' '.join(cmd[2:])}")
        result = subprocess.run(cmd, text=True, capture_output=True)
        tail = [ln for ln in (result.stdout or "").splitlines() if ln.strip()]
        print("\n".join(tail[-3:]))
        if result.returncode != 0:
            print(result.stderr)
            return result.returncode

    print("\n== Isi entity_id pada gold_labels.csv ==")
    counts = enrich_gold_entities()
    print(f"  baris: {counts['rows']:,}")
    print(f"  pasangan dalam entity sama: {counts['same_entity_true']:,}")
    print(f"  tidak terpetakan: {counts['unmapped']:,}")
    meta = read_meta(MASTER_PATH) or {}
    version = latest()
    metadata = {
        "model_version": meta.get("model_version") or (version.name if version else "unknown"),
        "pipeline_run_id": f"gold-rebuild-{meta.get('pipeline_run_id', '')}",
        "source_scope": meta.get("scope", "full"),
    }

    print("\n== Sync database ternormalisasi ==")
    from src.provenance import current_run_info

    cmd = [
        sys.executable,
        "scripts/sync_resolution_outputs.py",
        "--apply",
        "--model-version",
        metadata["model_version"],
        "--run-id",
        metadata["pipeline_run_id"],
    ]
    result = subprocess.run(cmd, text=True, capture_output=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        return result.returncode

    print("\nSelesai: gold_labels -> apply -> rebuild entity_map -> rebuild master -> sync database.")
    print(f"Metadata: {metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
