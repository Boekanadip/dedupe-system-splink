"""Tuntaskan siklus peninjauan label acuan: promosikan -> umpan balik -> terapkan -> kelompokkan ulang -> evaluasi.

Jalankan SETELAH mengisi label di pages/1_review.py. Modul ini menjalankan
serangkaian langkah yang biasanya harus dijalankan satu per satu, mengikuti
urutan run_all, dan berhenti jika terjadi kegagalan pertama.

    python -m src.close_gold_loop                 # hanya promosikan + umpan balik
    python -m src.close_gold_loop --apply         # + terapkan label gold ke keputusan
    python -m src.close_gold_loop --all           # terapkan + kelompokkan ulang + evaluasi
    python -m src.close_gold_loop --all --dry-run # hanya tampilkan perintah

Perintah promosi aman untuk antrean kosong: promote_gold() menolak menimpa
gold_labels.csv jika belum ada label (src/labels.py).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], dry_run: bool) -> None:
    print(f"\n== {' '.join(cmd)}")
    if dry_run:
        return
    result = subprocess.run(
        cmd, cwd=ROOT, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    sys.stdout.write(result.stdout or "")
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise SystemExit(f"failed: {' '.join(cmd)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote reviewed labels and apply them to decisions end to end."
    )
    parser.add_argument("--apply", action="store_true", help="Apply gold to decisions")
    parser.add_argument("--recluster", action="store_true", help="Re-cluster after apply")
    parser.add_argument("--evaluate", action="store_true", help="Re-run evaluate/scenario/threshold")
    parser.add_argument("--all", action="store_true", help="apply + recluster + evaluate")
    parser.add_argument("--dry-run", action="store_true", help="Print commands only")
    args = parser.parse_args()

    do_apply = args.apply or args.all or args.recluster or args.evaluate
    do_recluster = args.recluster or args.all or args.evaluate
    do_eval = args.evaluate or args.all

    # 1. Antrean/sampel positif palsu yang ditinjau -> gold_labels.csv (ditambahkan)
    run([sys.executable, "-m", "src.labels", "--promote"], args.dry_run)
    # 2. Pasangan yang ditinjau -> feedback.csv (hanya ditambahkan, kunci pair_id+model_version)
    run([sys.executable, "-m", "src.feedback"], args.dry_run)
    # 3. Label acuan -> keputusan (dengan pengaman; pasangan terblokir dilaporkan, tidak dipaksakan)
    if do_apply:
        cmd = [sys.executable, "-m", "src.apply_gold", "--apply"]
        if do_recluster:
            cmd.append("--recluster")
        run(cmd, args.dry_run)
    # 4. Lapisan evaluasi setelah keputusan berubah
    if do_eval:
        run([sys.executable, "-m", "src.evaluate"], args.dry_run)
        run([sys.executable, "-m", "src.scenario_eval"], args.dry_run)
        run([sys.executable, "-m", "src.threshold_eval", "--source", "gold", "--full"], args.dry_run)

    print("\nOK: gold loop closed.")


if __name__ == "__main__":
    main()
