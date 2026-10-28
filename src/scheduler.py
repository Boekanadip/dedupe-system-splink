from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from src.config import OUTPUT_DIR, PROJECT_ROOT
from src.health import build_health

LOCK_PATH = OUTPUT_DIR / ".scheduler_running"
HISTORY_PATH = OUTPUT_DIR / "scheduler_history.jsonl"
HEALTH_HISTORY_PATH = OUTPUT_DIR / "health_history.jsonl"


def acquire_scheduler_lock(note: str) -> bool:
    if not LOCK_PATH.parent.exists():
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        try:
            data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            age = time.time() - float(data.get("started_at", 0))
            if age < 7200:
                # lock masih aktif
                return False
            else:
                # lock basi, hapus
                LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            LOCK_PATH.unlink(missing_ok=True)
    # tulis lock baru
    lock_data = {
        "pid": os.getpid(),
        "started_at": time.time(),
        "note": note,
    }
    tmp = LOCK_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
    os.replace(tmp, LOCK_PATH)
    return True


def release_scheduler_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)


def _load_config(path: Path | None) -> dict:
    target = path or PROJECT_ROOT / "config" / "job.json"
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_job_run(config_path: Path | None) -> dict:
    """Jalankan satu kali python -m src.job_run (--config ...) dan kumpulkan hasil."""
    cmd = [sys.executable, "-u", "-m", "src.job_run"]
    if config_path:
        cmd += ["--config", str(config_path)]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.time() - started
        return {
            "command": " ".join(cmd[3:]),
            "returncode": proc.returncode,
            "stdout": proc.stdout[:4000] if proc.stdout else "",
            "stderr": proc.stderr[:2000] if proc.stderr else "",
            "seconds": round(elapsed, 2),
            "success": proc.returncode == 0,
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        }
    except Exception as exc:
        elapsed = time.time() - started
        return {
            "command": " ".join(cmd[3:]),
            "exception": str(exc),
            "seconds": round(elapsed, 2),
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
            "success": False,
        }


def _append_history(entry: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _append_health(entry: dict) -> None:
    """Satu baris metrik per iterasi. Ini yang填补 time-series history."""
    HEALTH_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HEALTH_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def run_once(config_path: Path | None, dry_run: bool) -> dict:
    note = f"scheduler run config={config_path.name if config_path else 'default'}"
    if dry_run:
        print(f"[DRY-RUN] {note}")
        print(f"  command: python -m src.job_run {'--config ' + str(config_path) if config_path else ''}")
        return {"note": note, "dry_run": True, "success": True, "timestamp": datetime.utcnow().isoformat(timespec="seconds")}
    if not acquire_scheduler_lock(note):
        return {
            "note": note + " (gagal — scheduler sudah berjalan)",
            "success": False,
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        }
    try:
        entry = _run_job_run(config_path)
        entry["note"] = note
        _append_history(entry)
        if entry.get("success"):
            _append_health(_health_snapshot())
        return entry
    finally:
        release_scheduler_lock()


def _health_snapshot() -> dict:
    """Ringkasan metrik saat ini untuk history (time-series)."""
    h = build_health()
    return {
        "generated_at": h.get("generated_at"),
        "status": h.get("status"),
        "alert_counts": h.get("alert_counts"),
        "review_queue_pending": h.get("model_output", {}).get("review_queue_pending"),
        "entities": h.get("entity", {}).get("entities"),
        "records": h.get("entity", {}).get("records"),
        "largest_entity": h.get("entity", {}).get("largest_entity"),
        "precision": (h.get("evaluation", {}).get("at_match_threshold") or {}).get("precision"),
        "recall": (h.get("evaluation", {}).get("at_match_threshold") or {}).get("recall"),
    }


def run_daemon(interval_seconds: int, config_path: Path | None, dry_run: bool) -> None:
    import signal as _signal
    def _shutdown(signum, frame):
        print("\n[SIGNAL] Menutup daemon scheduler.")
        sys.exit(0)
    _signal.signal(_signal.SIGINT, _shutdown)
    _signal.signal(_signal.SIGTERM, _shutdown)

    print(f"[DAEMON] Scheduler berjalan (interval {interval_seconds}s). Tekan Ctrl-C untuk berhenti.")
    while True:
        try:
            entry = run_once(config_path, dry_run)
            print(f"[{entry.get('timestamp', '')}] Scheduler selesai: {'sukses' if entry.get('success') else 'gagal'}")
            if not dry_run:
                # setelah sukses (atau gagal), tunggu interval
                time.sleep(interval_seconds)
            else:
                # dry-run: jangan tidur
                break
        except KeyboardInterrupt:
            print("\n[INFO] Dihentikan oleh pengguna.")
            break
        except Exception as e:
            print(f"[ERROR] Scheduler iterasi gagal: {e}")
            time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jalankan job_run periodik (scheduler).")
    parser.add_argument("--once", action="store_true", help="Jalankan satu kali (default)")
    parser.add_argument("--daemon", action="store_true", help="Jalankan dalam loop daemon")
    parser.add_argument("--interval", type=int, default=300,
                        help="Interval antar iterasi (detik), hanya jika --daemon")
    parser.add_argument("--config", type=Path, default=None,
                        help="Path ke config JSON (misalnya config/job.json)")
    parser.add_argument("--dry-run", action="store_true", help="Cetak command, jangan jalankan")
    args = parser.parse_args()

    if args.once or not (args.daemon or args.interval):
        # default: sekali
        result = run_once(args.config, args.dry_run)
        sys.exit(0 if result.get("success", True) else 1)
    else:
        run_daemon(args.interval, args.config, args.dry_run)


if __name__ == "__main__":
    main()
