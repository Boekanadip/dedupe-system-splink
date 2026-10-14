"""Single entry point: pull a database table into the pipeline in one call.

Phase 2 of the DB-input work. Before this, feeding the pipeline from a database
took two manual commands (db_export then incremental). This wraps both behind
one invocation with a machine-readable summary and a real exit code, so a
scheduler or CI job can call it and react to the result.

What it does, in order:
  1. export_batch()  — fetch new rows (watermark-aware), write CSV, register.
  2. incremental     — stage the batch: score new x new and new x old, write a
                       merge proposal. Nothing is applied without human review.
  3. summary         — outputs/job_run_summary.json with runtime, counts, exit
                       status. The same shape a scheduler would scrape.

Config precedence: CLI flag > environment variable > config file > default.
Credentials never live in the config file; DB_SOURCE can point at a DSN that
reads them from the environment on the database side.

Usage:
    python -m src.job_run --source data/synthetic/crm.duckdb --table crm_customers
    python -m src.job_run --config config/job.json
    python -m src.job_run --source ... --table ... --mode apply
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import OUTPUT_DIR, PROJECT_ROOT, atomic_write_json
from .db_export import export_batch

SUMMARY_PATH = OUTPUT_DIR / "job_run_summary.json"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "job.json"


def _load_config(path: Path | None) -> dict:
    """Read a JSON config file. Missing or broken config falls back to {} so a
    flag-only invocation still works."""
    target = path or DEFAULT_CONFIG
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"Config {target} is unreadable: {exc}") from None


def _resolve(args: argparse.Namespace, config: dict, key: str, env: str, default=None):
    """CLI flag > env var > config file > default."""
    cli = getattr(args, key, None)
    if cli is not None:
        return cli
    if os.environ.get(env):
        return os.environ[env]
    return config.get(key, default)


def run_incremental(batch_file: str, mode: str, date_order: str) -> dict:
    """Invoke src.incremental as a subprocess and capture its log.

    A subprocess, not an import, because incremental acquires the pipeline
    lock, sets PIPELINE_STAGING for its own children, and can exit non-zero.
    Running it in-process would leak that environment into the caller.
    """
    command = [sys.executable, "-u", "-m", "src.incremental", "--batch", batch_file]
    if mode == "stage":
        command.append("--stage")
    elif mode == "apply":
        command.append("--apply")
    if date_order != "auto":
        command += ["--date-order", date_order]

    started = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return {
        "command": " ".join(command[3:]),
        "returncode": proc.returncode,
        "seconds": round(time.perf_counter() - started, 2),
        "log": proc.stdout or "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull a database table into the pipeline in one call."
    )
    parser.add_argument("--config", default=None, help="Path to a JSON config file.")
    parser.add_argument("--source", default=None, help="DSN or path to the database.")
    parser.add_argument("--table", default=None, help="Table or view to read.")
    parser.add_argument(
        "--mode",
        choices=["stage", "apply", "export-only"],
        default=None,
        help="stage = propose merges (default). apply = commit a staged proposal. "
        "export-only = fetch and register, skip incremental.",
    )
    parser.add_argument(
        "--date-order",
        choices=["auto", "dmy", "mdy"],
        default=None,
        help="Day/month order for ambiguous dates.",
    )
    parser.add_argument(
        "--no-watermark",
        action="store_true",
        help="Ignore the saved watermark and fetch every row.",
    )
    args = parser.parse_args()

    config = _load_config(Path(args.config) if args.config else None)
    source = _resolve(args, config, "source", "DB_SOURCE")
    table = _resolve(args, config, "table", "DB_TABLE")
    mode = _resolve(args, config, "mode", "JOB_MODE", "stage")
    date_order = _resolve(args, config, "date_order", "JOB_DATE_ORDER", "auto")
    use_watermark = not args.no_watermark and config.get("watermark", True)

    if not source or not table:
        raise SystemExit(
            "No database source configured. Pass --source and --table, set "
            "DB_SOURCE/DB_TABLE, or create config/job.json."
        )

    started = time.perf_counter()
    summary: dict = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "table": table,
        "mode": mode,
        "date_order": date_order,
        "watermark": use_watermark,
        "steps": [],
        "status": "running",
        "exit_code": None,
    }

    print(f"== job_run: {table} from {source} (mode={mode}, watermark={use_watermark})")

    # --- step 1: export
    print("\n== export")
    try:
        exported = export_batch(
            source, table, use_watermark=use_watermark, defer_watermark=True
        )
    except SystemExit as exc:
        summary["status"] = "failed"
        summary["exit_code"] = 2
        summary["error"] = str(exc)
        _finish(summary, started)
        raise
    summary["steps"].append({"step": "export", **{k: v for k, v in exported.items() if k not in ("columns", "latest_mark")}})
    summary["rows"] = exported["rows"]

    if exported["status"] == "noop":
        print(exported["message"])
        summary["status"] = "noop"
        summary["exit_code"] = 0
        _finish(summary, started)
        return

    if exported["status"] == "already_registered":
        print(exported["message"])
    else:
        print(f"  {exported['rows']:,} rows -> {exported['batch_file']} (batch {exported['batch_id']})")

    # --- step 2: incremental
    if mode == "export-only":
        _advance_watermark(source, table, exported, summary)
        print("\n== incremental skipped (export-only)")
        summary["status"] = "exported"
        summary["exit_code"] = 0
        _finish(summary, started)
        return

    print(f"\n== incremental ({mode})")
    result = run_incremental(exported["batch_file"], mode, date_order)
    summary["steps"].append(
        {"step": "incremental", "returncode": result["returncode"], "seconds": result["seconds"]}
    )
    if result["returncode"] != 0:
        print(result["log"][-4000:])
        summary["status"] = "failed"
        summary["exit_code"] = result["returncode"]
        summary["error"] = "incremental failed; see log tail in this summary"
        summary["log_tail"] = result["log"][-4000:]
        _finish(summary, started)
        raise SystemExit(result["returncode"])

    _advance_watermark(source, table, exported, summary)

    # Pull the merge counts the staged proposal recorded, when present.
    counts = _staged_counts(exported["batch_file"])
    if counts:
        summary.update(counts)
    summary["status"] = "succeeded"
    summary["exit_code"] = 0
    _finish(summary, started)
    print(f"\n== done in {summary['total_seconds']}s")


def _advance_watermark(source: str, table: str, exported: dict, summary: dict) -> None:
    """Move the watermark only once the whole job succeeded.

    export_batch deferred this so a failed incremental cannot consume rows and
    leave the registered batch unreachable by a re-run.
    """
    mark = exported.get("latest_mark")
    if mark is None:
        return
    from .db_source import write_watermark

    write_watermark(source, table, {"updated_at": mark})
    summary["watermark_advanced"] = mark
    print(f"  watermark advanced to {mark}")


def _staged_counts(batch_file: str) -> dict:
    """Read the staged proposal's action counts, when it exists."""
    from .config import OUTPUT_DIR as _OUT

    path = _OUT / "staging" / f"{batch_file}.parquet"
    if not path.exists():
        return {}
    try:
        import pandas as pd

        staging = pd.read_parquet(path, columns=["action"])
        counts = staging["action"].value_counts().to_dict()
        return {
            "proposed_matches": int(counts.get("match", 0)),
            "proposed_new": int(counts.get("new", 0)),
            "staged_records": int(len(staging)),
        }
    except Exception:
        return {}


def _finish(summary: dict, started: float) -> None:
    summary["total_seconds"] = round(time.perf_counter() - started, 2)
    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(summary, SUMMARY_PATH)
    print(f"Summary: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()