"""Close the gold-review loop: promote -> feedback -> apply -> recluster -> evaluate.

Run this AFTER filling labels in pages/1_review.py. It chains the steps that
otherwise have to be run one by one, in the order run_all uses, and stops at
the first failure.

    python -m src.close_gold_loop                 # promote + feedback only
    python -m src.close_gold_loop --apply         # + apply gold to decisions
    python -m src.close_gold_loop --all           # apply + recluster + evaluate
    python -m src.close_gold_loop --all --dry-run # print the commands only

promote is safe on an empty queue: promote_gold() refuses to overwrite
gold_labels.csv when nothing is labelled (src/labels.py).
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
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    sys.stdout.write(result.stdout)
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

    # 1. Reviewed queue/FP-sample -> gold_labels.csv (append semantics)
    run([sys.executable, "-m", "src.labels", "--promote"], args.dry_run)
    # 2. Reviewed pairs -> feedback.csv (append-only, keyed pair_id+model_version)
    run([sys.executable, "-m", "src.feedback"], args.dry_run)
    # 3. Gold -> decisions (guarded; blocked pairs are reported, not forced)
    if do_apply:
        cmd = [sys.executable, "-m", "src.apply_gold", "--apply"]
        if do_recluster:
            cmd.append("--recluster")
        run(cmd, args.dry_run)
    # 4. Evaluation layers after the decision changes
    if do_eval:
        run([sys.executable, "-m", "src.evaluate"], args.dry_run)
        run([sys.executable, "-m", "src.scenario_eval"], args.dry_run)
        run([sys.executable, "-m", "src.threshold_eval", "--source", "gold", "--full"], args.dry_run)

    print("\nOK: gold loop closed.")


if __name__ == "__main__":
    main()
