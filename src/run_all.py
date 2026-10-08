from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import (
    ENTITY_MAP_PATH,
    MASTER_PATH,
    OUTPUT_DIR,
    SMOKE_SAMPLE_SIZE,
    predictions_path,
    read_meta,
    scope_of,
)

RUN_SUMMARY_PATH = OUTPUT_DIR / "run_summary.json"

STEPS = [
    ("profiling", ["profiling"]),
    ("standardize", ["standardize"]),
    ("labels_silver", ["labels", "--silver-only"]),
    ("blocking_benchmark", ["blocking_benchmark"]),
    ("splink_model", ["splink_model"]),
    ("labels_review_queue", ["labels"]),
    ("clustering", ["clustering"]),
    ("master_record", ["master_record"]),
    ("evaluate", ["evaluate"]),
]


def run_step(name: str, module_args: list[str], timeout: float | None) -> dict:
    command = [sys.executable, "-u", "-m", f"src.{module_args[0]}", *module_args[1:]]
    print(f"\n{'=' * 70}\n== {name}\n== {' '.join(command[3:])}\n{'=' * 70}", flush=True)
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8:replace"},
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"Step {name!r} exceeded {timeout}s and was killed. "
            "Inspect the log above for the last completed action, then rerun "
            "with a larger --step-timeout if it is genuinely slow."
        ) from None
    elapsed = round(time.perf_counter() - started, 2)

    if result.returncode != 0:
        raise SystemExit(f"Step {name!r} failed with exit code {result.returncode}")
    return {"step": name, "command": " ".join(command[3:]), "seconds": elapsed}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the deduplication pipeline end to end.")
    parser.add_argument(
        "--sample",
        action="store_true",
        help=f"Run on the {SMOKE_SAMPLE_SIZE} row sample instead of the full dataset.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Let a --sample run overwrite full-run artifacts. Off by default so a "
        "quick smoke test cannot destroy a full pipeline result.",
    )
    parser.add_argument(
        "--date-order",
        choices=["auto", "dmy", "mdy"],
        default="auto",
        help=(
            "Day/month order handed to the standardize step. 'auto' keeps the "
            "default (derive from unambiguous rows, refuse when there is no "
            "evidence). A UI that asked the user passes its answer here."
        ),
    )
    parser.add_argument(
        "--reuse-model",
        metavar="PATH",
        default=None,
        help=(
            "Score with a saved model version instead of retraining "
            "(MASTER_CONTEXT section 15). 'latest' picks the newest saved version. "
            "Off by default: a fresh run trains and saves a new version."
        ),
    )
    parser.add_argument(
        "--step-timeout",
        type=float,
        default=1800.0,
        help="Kill a pipeline step that produces no completion within this many "
        "seconds. 0 disables the guard. Default 1800s: the slowest measured "
        "step (EM training) takes ~2 minutes on 51k rows.",
    )
    args = parser.parse_args()
    step_timeout = args.step_timeout if args.step_timeout > 0 else None

    started = time.perf_counter()
    full = not args.sample
    flag = ["--full"] if full else ["--sample"]
    if args.force and full:
        raise SystemExit("--force only applies to a --sample run.")

    steps = []
    for name, module_args in STEPS:
        if name == "clustering" and args.force:
            steps.append((name, [*module_args, *flag, "--force"]))
        elif name == "splink_model" and args.reuse_model:
            steps.append((name, [*module_args, *flag, "--reuse-model", args.reuse_model]))
        elif name in ("blocking_benchmark", "splink_model", "clustering"):
            steps.append((name, [*module_args, *flag]))
        elif name == "standardize" and args.date_order != "auto":
            steps.append((name, [*module_args, "--date-order", args.date_order]))
        elif name in ("labels_silver", "labels_review_queue"):
            extra = ["--full"] if full else []
            if name == "labels_silver" and not full:
                extra.append("--silver-only")
            steps.append((name, [*module_args, *extra]))
        elif name == "evaluate":
            steps.append((name, module_args if full else [*module_args, "--sample"]))
        else:
            steps.append((name, module_args))

    results = []
    for name, module_args in steps:
        results.append(run_step(name, module_args, step_timeout))

    from .model_lifecycle import latest

    model_version = latest().name if latest() else None

    expected = scope_of(full)
    checks = {
        "predictions": read_meta(predictions_path(full=full)),
        "entity_map": read_meta(ENTITY_MAP_PATH),
        "master_customers": read_meta(MASTER_PATH),
    }
    mismatches = {
        name: meta.get("scope")
        for name, meta in checks.items()
        if meta and meta.get("scope") != expected
    }
    if mismatches:
        raise SystemExit(f"Scope mismatch, expected {expected!r}: {mismatches}")

    summary = {
        "scope": expected,
        "total_seconds": round(time.perf_counter() - started, 2),
        "model_version": model_version,
        "reused_model": args.reuse_model,
        "steps": results,
        "artifacts": {
            "predictions": predictions_path(full=full).name,
            "entity_map": ENTITY_MAP_PATH.name,
            "master_customers": MASTER_PATH.name,
        },
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RUN_SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{'=' * 70}")
    for row in results:
        print(f"  {row['step']:24s} {row['seconds']:8.2f}s  {row['command']}")
    print(f"  {'TOTAL':24s} {summary['total_seconds']:8.2f}s   scope={expected}")
    print(f"Saved: {RUN_SUMMARY_PATH}")


if __name__ == "__main__":
    main()
