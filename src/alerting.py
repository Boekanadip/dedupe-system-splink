from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Set, Tuple

from src.config import OUTPUT_DIR, PROJECT_ROOT
from src.health import build_health

WEBHOOK_URL = os.getenv("DEDUP_WEBHOOK_URL", "")
COOLDOWN_SECONDS = int(os.getenv("DEDUP_ALERT_COOLDOWN_SECONDS", "3600"))

SENT_TRACK_PATH = OUTPUT_DIR / ".alert_sent.json"
HISTORY_PATH = OUTPUT_DIR / "alerting_history.jsonl"


def _load_sent() -> dict:
    """Kembalikan map signature -> timestamp Unix epoch."""
    if not SENT_TRACK_PATH.exists():
        return {}
    try:
        return json.loads(SENT_TRACK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_sent(sent: dict) -> None:
    SENT_TRACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENT_TRACK_PATH.write_text(json.dumps(sent, indent=2, default=str), encoding="utf-8")


def _signature(alert: dict) -> str:
    # Kunci unik berdasarkan level, source, dan pesan
    key = f"{alert.get('level')}|{alert.get('source')}|{alert.get('message')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _should_send(sig: str, sent: dict) -> bool:
    ts = sent.get(sig)
    if not ts:
        return True
    if time.time() - ts > COOLDOWN_SECONDS:
        return True
    return False


def _record_sent(sig: str, sent: dict) -> None:
    sent[sig] = time.time()
    _save_sent(sent)


def _send_webhook(payload: dict) -> bool:
    if not WEBHOOK_URL:
        print("[ALERT] Dedup_WEBHOOK_URL tidak diset — skip mengirim webhook.")
        return False
    import requests
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"[ALERT] Webhook terkirim: {resp.status_code}")
            return True
        else:
            print(f"[ALERT] Webhook gagal: HTTP {resp.status_code} – {resp.text[:200]}")
            return False
    except Exception as exc:
        print(f"[ALERT] Webhook exception: {exc}")
        return False


def _append_history(entry: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def run_once(dry_run: bool) -> dict:
    health = build_health()
    alerts = health.get("alerts") or []
    sent = _load_sent()
    sent_any = False
    for alert in alerts:
        sig = _signature(alert)
        if not _should_send(sig, sent):
            print(f"[ALERT] Skipping (cooldown): {alert.get('level')}:{alert.get('source')} - {alert.get('message')[:80]}...")
            continue
        # Siapkan payload Slack-compatible
        payload = {
            "text": f"ALERT {alert.get('level').upper()}: {alert.get('source')} - {alert.get('message')}",
            "attachments": [{
                "color": "danger" if alert.get("level") == "critical" else "warning",
                "fields": [
                    {"title": "Level", "value": alert.get("level"), "short": True},
                    {"title": "Source", "value": alert.get("source"), "short": True},
                    {"title": "Message", "value": alert.get("message"), "short": False},
                    {"title": "Generated at", "value": health.get("generated_at"), "short": True},
                ],
                "ts": int(time.time()),
            }],
        }
        if dry_run:
            print(f"[DRY-RUN] Kirim webhook ke {WEBHOOK_URL}: {payload['text']}")
            sent_any = True
            _record_sent(sig, sent)
        else:
            if _send_webhook(payload):
                sent_any = True
                _record_sent(sig, sent)
            else:
                print(f"[ALERT] Gagal mengirim webhook, tidak mencatat sebagai terkirim (maybe transient).")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "alerts_count": len(alerts),
        "new_alerts_sent": sent_any,
        "webhook_url_set": bool(WEBHOOK_URL),
        "dry_run": dry_run,
    }
    _append_history(entry)
    return entry


def run_daemon(interval_seconds: int, dry_run: bool) -> None:
    import signal as _signal
    def _shutdown(signum, frame):
        print("\n[SIGNAL] Menutup daemon alerting.")
        sys.exit(0)
    _signal.signal(_signal.SIGINT, _shutdown)
    _signal.signal(_signal.SIGTERM, _shutdown)

    print(f"[ALERT] Daemon alerting berjalan (interval {interval_seconds}s). Tekan Ctrl-C untuk berhenti.")
    while True:
        try:
            entry = run_once(dry_run)
            print(f"[{entry['timestamp']}] Alerting selesai: {entry['alerts_count']} alerts, baru terkirim: {entry['new_alerts_sent']}")
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\n[INFO] Dihentikan oleh pengguna.")
            break
        except Exception as e:
            print(f"[ERROR] Alerting iterasi gagal: {e}")
            time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Alerting dan webhook untuk health check.")
    parser.add_argument("--once", action="store_true", help="Jalankan satu kali (default)")
    parser.add_argument("--daemon", action="store_true", help="Jalankan dalam loop daemon")
    parser.add_argument("--interval", type=int, default=300,
                        help="Interval antar iterasi (detik), hanya jika --daemon")
    parser.add_argument("--dry-run", action="store_true", help="Cetak action, jangan kirim webhook")
    args = parser.parse_args()

    if args.once or not (args.daemon or args.interval):
        result = run_once(args.dry_run)
        sys.exit(0)
    else:
        run_daemon(args.interval, args.dry_run)


if __name__ == "__main__":
    main()