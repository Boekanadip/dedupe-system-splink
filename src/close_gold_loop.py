
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

    run([sys.executable, "-m", "src.labels", "--promote"], args.dry_run)
    run([sys.executable, "-m", "src.feedback"], args.dry_run)
    if do_apply:
        cmd = [sys.executable, "-m", "src.apply_gold", "--apply"]
        if do_recluster:
            cmd.append("--recluster")
        run(cmd, args.dry_run)
    if do_eval:
        run([sys.executable, "-m", "src.evaluate"], args.dry_run)
        run([sys.executable, "-m", "src.scenario_eval"], args.dry_run)
        run([sys.executable, "-m", "src.threshold_eval", "--source", "gold", "--full"], args.dry_run)

    print("\nOK: gold loop closed.")


if __name__ == "__main__":
    main()
