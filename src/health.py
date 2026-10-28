
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    MATCH_THRESHOLD,
    REVIEW_THRESHOLD,
    ENTITY_MAP_PATH,
    MASTER_PATH,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    predictions_path,
    pipeline_locked,
    read_meta,
)

QUEUE_PATH = Path(__file__).resolve().parents[1] / "data" / "labels" / "review_queue.csv"
GOLD_PATH = Path(__file__).resolve().parents[1] / "data" / "labels" / "gold_labels.csv"
WATERMARK_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "db_watermark.json"
BATCH_REGISTRY = Path(__file__).resolve().parents[1] / "data" / "processed" / "batch_registry.json"
STALE_PATH = OUTPUT_DIR / "db_stale_entities.json"

# Threshold alert (dari BACKEND_HANDOFF.md Bagian 1)
ALERTS = {
    "review_pending_max": 500,
    "largest_entity_max": 100,
    "precision_min": 0.95,
    "recall_min": 0.95,
    "watermark_age_max_hours": 24,
    "auto_match_rate_max": 0.05,
    "blocking_recall_ceiling_min": 0.99,
}


def _load_json(path: Path) -> dict | list | None:
    """Baca JSON. None jika file tidak ada atau rusak."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _age_hours(ts: float) -> float:
    return round((time.time() - ts) / 3600, 2)


def _mtime_hours(path: Path) -> float | None:
    if not path.exists():
        return None
    return _age_hours(path.stat().st_mtime)


def _pipeline_health() -> dict:
    lock = pipeline_locked()
    run = _load_json(OUTPUT_DIR / "run_summary.json")
    job = _load_json(OUTPUT_DIR / "job_run_summary.json")
    retrain_lock = OUTPUT_DIR / ".retraining"

    out: dict = {
        "pipeline_locked": lock is not None,
        "pipeline_lock_note": lock.get("note") if lock else None,
        "last_run": None,
        "last_job": None,
        "retrain_lock_active": retrain_lock.exists(),
    }
    if run:
        out["last_run"] = {
            "scope": run.get("scope"),
            "model_version": run.get("model_version"),
            "total_seconds": run.get("total_seconds"),
            "steps": [
                {"step": s.get("step"), "seconds": s.get("seconds")}
                for s in run.get("steps", [])
            ],
        }
    if job:
        out["last_job"] = {
            "status": job.get("status"),
            "exit_code": job.get("exit_code"),
            "total_seconds": job.get("total_seconds"),
            "finished_at": job.get("finished_at"),
            "source": job.get("source"),
            "table": job.get("table"),
        }
    return out


def _data_quality() -> dict:
    report = _load_json(OUTPUT_DIR / "upload_validation_report.json")
    if report is None:
        return {"available": False}
    return {
        "available": True,
        "status": report.get("status"),
        "rows": report.get("rows"),
        "blocking": report.get("blocking", []),
        "warnings": report.get("warnings", []),
        "exact_duplicate_rows": report.get("exact_duplicate_rows"),
        "needs_date_answer": any(
            v.get("needs_answer") for v in report.get("date_formats", {}).values()
        ),
    }


def _model_output() -> dict:
    from .config import active_path

    preds_path = active_path(predictions_path(full=True))
    meta = read_meta(preds_path)
    if not meta:
        return {"available": False}

    queue_pending = None
    if QUEUE_PATH.exists():
        try:
            import pandas as pd

            q = pd.read_csv(QUEUE_PATH, low_memory=False)
            queue_pending = int((q.get("review_status") == "pending").sum())
        except Exception:
            queue_pending = None

    return {
        "available": True,
        "model_version": meta.get("model_version"),
        "scope": meta.get("scope"),
        "input_rows": meta.get("input_rows"),
        "pairs_scored": meta.get("pairs_scored"),
        "match_threshold": meta.get("match_threshold", MATCH_THRESHOLD),
        "review_threshold": meta.get("review_threshold", REVIEW_THRESHOLD),
        "trained": meta.get("trained"),
        "review_queue_pending": queue_pending,
    }


def _entity() -> dict:
    if not ENTITY_MAP_PATH.exists():
        return {"available": False}
    meta = read_meta(ENTITY_MAP_PATH)
    master_meta = read_meta(MASTER_PATH)
    if not meta:
        return {"available": False}
    return {
        "available": True,
        "records": meta.get("records"),
        "entities": meta.get("entities"),
        "match_edges": meta.get("match_edges"),
        "review_pairs": meta.get("review_pairs"),
        "records_merged_away": meta.get("records_merged_away"),
        "largest_entity": meta.get("largest_entity"),
        "singleton_entities": meta.get("singleton_entities"),
        "master_entities": master_meta.get("entities") if master_meta else None,
    }


def _db_ingestion() -> dict:
    wm = _load_json(WATERMARK_PATH)
    refresh = _load_json(OUTPUT_DIR / "db_refresh_report.json")
    stale = _load_json(STALE_PATH)
    registry = _load_json(BATCH_REGISTRY)

    out: dict = {"available": wm is not None}
    if wm:
        out["watermarks"] = {}
        for key, val in wm.items():
            updated = val.get("updated_at") if isinstance(val, dict) else str(val)
            out["watermarks"][key] = {
                "updated_at": updated,
                "age_hours": _mtime_hours(WATERMARK_PATH),
            }
    if refresh:
        out["last_refresh"] = {
            "status": refresh.get("status"),
            "changed_rows": refresh.get("changed_rows"),
            "new_rows": refresh.get("new_rows"),
            "update_rows": refresh.get("update_rows"),
            "key_map_size": refresh.get("key_map_size"),
        }
    out["stale_entities"] = len(stale) if isinstance(stale, list) else 0
    if registry:
        out["batches"] = len(registry.get("batches", []))
        out["registered_rows"] = sum(b.get("rows", 0) for b in registry.get("batches", []))
    return out


def _evaluation() -> dict:
    report = _load_json(OUTPUT_DIR / "threshold_evaluation_gold.json")
    if report is None:
        return {"available": False}

    at_match = next(
        (r for r in report.get("results", []) if r.get("threshold") == MATCH_THRESHOLD),
        None,
    )
    return {
        "available": True,
        "label_source": report.get("label_source"),
        "positives": report.get("positives"),
        "negatives": report.get("negatives"),
        "at_match_threshold": (
            {
                "precision": at_match.get("precision"),
                "recall": at_match.get("recall"),
                "f1": at_match.get("f1"),
                "tp": at_match.get("tp"),
                "fp": at_match.get("fp"),
                "fn": at_match.get("fn"),
            }
            if at_match
            else None
        ),
    }


def _decision_distribution() -> dict:
    """Dari evaluation_report.json (lebih lengkap dari meta)."""
    report = _load_json(OUTPUT_DIR / "evaluation_report.json")
    if report is None:
        return {"available": False}
    decision = report.get("decision", {})
    blocking = report.get("blocking", {})
    entity = report.get("entity", {})
    return {
        "available": True,
        "counts": decision.get("counts"),
        "rates": decision.get("rates"),
        "candidate_pairs": blocking.get("candidate_pairs"),
        "blocking_recall_ceiling": blocking.get("blocking_recall_ceiling"),
        "records": entity.get("records"),
        "entities": entity.get("entities"),
        "largest_entity": entity.get("largest_entity"),
        "truth_pairs_split": entity.get("truth_pairs_split_across_entities"),
        "entities_mixing_devices": entity.get("entities_mixing_two_device_ids"),
    }


def _check_alerts(health: dict) -> list[dict]:
    alerts: list[dict] = []

    # Pipeline
    job = health["pipeline"].get("last_job")
    if job and job.get("status") not in (None, "succeeded", "noop"):
        alerts.append({
            "level": "critical",
            "source": "pipeline",
            "message": f"Last job status={job['status']}, exit_code={job.get('exit_code')}",
        })

    # Review queue
    pending = health["model_output"].get("review_queue_pending")
    if pending is not None and pending > ALERTS["review_pending_max"]:
        alerts.append({
            "level": "warning",
            "source": "review_queue",
            "message": f"Review queue has {pending} pending pairs (max {ALERTS['review_pending_max']})",
        })

    # Entity
    largest = health["entity"].get("largest_entity")
    if largest is not None and largest > ALERTS["largest_entity_max"]:
        alerts.append({
            "level": "warning",
            "source": "entity",
            "message": f"Largest entity has {largest} records (max {ALERTS['largest_entity_max']})",
        })

    # Evaluation
    eval_at = health["evaluation"].get("at_match_threshold")
    if eval_at:
        if eval_at.get("precision") is not None and eval_at["precision"] < ALERTS["precision_min"]:
            alerts.append({
                "level": "warning",
                "source": "evaluation",
                "message": f"Precision @ {MATCH_THRESHOLD} = {eval_at['precision']} (min {ALERTS['precision_min']})",
            })
        if eval_at.get("recall") is not None and eval_at["recall"] < ALERTS["recall_min"]:
            alerts.append({
                "level": "warning",
                "source": "evaluation",
                "message": f"Recall @ {MATCH_THRESHOLD} = {eval_at['recall']} (min {ALERTS['recall_min']})",
            })

    # Decision rate
    rates = health["decision_distribution"].get("rates") or {}
    auto_rate = rates.get("auto_match_rate")
    if auto_rate is not None and auto_rate > ALERTS["auto_match_rate_max"]:
        alerts.append({
            "level": "warning",
            "source": "model_output",
            "message": f"Auto-match rate {auto_rate:.4%} exceeds {ALERTS['auto_match_rate_max']:.1%}",
        })

    # Blocking recall ceiling
    ceiling = health["decision_distribution"].get("blocking_recall_ceiling")
    if ceiling is not None and ceiling < ALERTS["blocking_recall_ceiling_min"]:
        alerts.append({
            "level": "warning",
            "source": "blocking",
            "message": f"Blocking recall ceiling {ceiling} < {ALERTS['blocking_recall_ceiling_min']}",
        })

    # DB ingestion
    wm_info = health["db_ingestion"].get("watermarks") or {}
    for source, info in wm_info.items():
        age = info.get("age_hours")
        if age is not None and age > ALERTS["watermark_age_max_hours"]:
            alerts.append({
                "level": "warning",
                "source": "db_ingestion",
                "message": f"Watermark for {source} is {age}h old (max {ALERTS['watermark_age_max_hours']}h)",
            })

    stale = health["db_ingestion"].get("stale_entities", 0)
    if stale > 0:
        alerts.append({
            "level": "warning",
            "source": "db_ingestion",
            "message": f"{stale} stale entities pending review (db_stale_entities.json)",
        })

    return alerts


def build_health() -> dict:
    health = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thresholds": {
            "match": MATCH_THRESHOLD,
            "review": REVIEW_THRESHOLD,
        },
        "alert_config": ALERTS,
        "pipeline": _pipeline_health(),
        "data_quality": _data_quality(),
        "model_output": _model_output(),
        "entity": _entity(),
        "db_ingestion": _db_ingestion(),
        "evaluation": _evaluation(),
        "decision_distribution": _decision_distribution(),
    }
    health["alerts"] = _check_alerts(health)

    critical = sum(1 for a in health["alerts"] if a["level"] == "critical")
    warning = sum(1 for a in health["alerts"] if a["level"] == "warning")
    health["status"] = "critical" if critical else ("degraded" if warning else "healthy")
    health["alert_counts"] = {"critical": critical, "warning": warning}
    return health


def main() -> None:
    parser = argparse.ArgumentParser(description="Health check: output JSON metrics.")
    parser.add_argument("--pretty", action="store_true", help="Indented JSON output.")
    args = parser.parse_args()

    health = build_health()
    indent = 2 if args.pretty else None
    print(json.dumps(health, indent=indent, default=str))


if __name__ == "__main__":
    main()
