from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from datetime import datetime

from .config import (
    ENTITY_MAP_PATH,
    MASTER_PATH,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    SMOKE_SAMPLE_SIZE,
    STAGING_ENV,
    acquire_pipeline_lock,
    discard_staged,
    finalize_staged,
    predictions_path,
    read_meta,
    release_pipeline_lock,
    scope_of,
    atomic_write_parquet,
    atomic_write_json,
)

RUN_SUMMARY_PATH = OUTPUT_DIR / "run_summary.json"

CHECKPOINT_PATH = OUTPUT_DIR / ".run_checkpoint.json"


def _load_checkpoint() -> dict:
    if not CHECKPOINT_PATH.exists():
        return {}
    try:
        import json as _json

        data = _json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _mark_done(step: str, elapsed: float) -> None:
    data = _load_checkpoint()
    data[step] = {"done_at": time.time(), "seconds": elapsed}
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, CHECKPOINT_PATH)


def _clear_checkpoint() -> None:
    CHECKPOINT_PATH.unlink(missing_ok=True)


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
    ("version_gold_scores", ["version_gold_scores"]),
]


def run_step(name: str, module_args: list[str], timeout: float | None) -> dict:
    command = [sys.executable, "-u", "-m", f"src.{module_args[0]}", *module_args[1:]]
    print(f"\n{'=' * 70}\n== {name}\n== {' '.join(command[3:])}\n{'=' * 70}", flush=True)
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8:replace", STAGING_ENV: "1"},
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
        elif name == "version_gold_scores":
            # Full only: gold comparison needs full-scope predictions.
            if full:
                steps.append((name, [*module_args, "--limit", "6"]))
        else:
            steps.append((name, module_args))

    results = []
    acquire_pipeline_lock(note=f"run_all scope={'full' if full else 'sample'}")
    try:
        orphaned = discard_staged()
        if orphaned:
            print(f"Membersihkan {orphaned} file staging yatim dari run sebelumnya.")
        for name, module_args in steps:
            results.append(run_step(name, module_args, step_timeout))
    except BaseException:
        discarded = discard_staged()
        if discarded:
            print(f"\nRun gagal — {discarded} file staging dibuang, state lama tetap utuh.")
        raise
    finally:
        release_pipeline_lock()

    swapped = finalize_staged()
    if swapped:
        print(f"\nCommit: {swapped} artefak ditukar serentak.")

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
    atomic_write_json(summary, RUN_SUMMARY_PATH)

    if full:
        try:
            import pandas as pd

            history_path = OUTPUT_DIR / "incremental_history.jsonl"
            try:
                processed = len(pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id"]))
            except Exception:
                processed = 0
            try:
                total_entities = int(
                    pd.read_parquet(ENTITY_MAP_PATH, columns=["entity_id"])["entity_id"].nunique()
                )
            except Exception:
                total_entities = 0
            entry = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "batch": f"retrain:{model_version or 'unknown'}",
                "rows": 0,
                "new_records": 0,
                "new_entities": 0,
                "entity_merges": [],
                "affected_entities": 0,
                "match_edges": 0,
                "review_pairs_added": 0,
                "runtime_seconds": summary["total_seconds"],
                "source": "run_all",
                "scope": expected,
                "processed_records": processed,
                "total_entities": total_entities,
            }
            with open(history_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
            print(f"History appended: {history_path.name} -> {entry['batch']}")
        except Exception as exc:
            print(f"History append skipped: {exc}")

    print(f"\n{'=' * 70}")
    for row in results:
        print(f"  {row['step']:24s} {row['seconds']:8.2f}s  {row['command']}")
    print(f"  {'TOTAL':24s} {summary['total_seconds']:8.2f}s   scope={expected}")
    print(f"Saved: {RUN_SUMMARY_PATH}")


if __name__ == "__main__":
    main()
