"""Monitoring and alerting metrics for CRM entity resolution."""
import json
import os
import requests
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from pathlib import Path

# Load .env file
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

from src.db import get_connection

METRICS_FILE = Path("outputs/metrics.json")
API_URL = os.environ.get("API_URL", "http://localhost:8000")


def get_db_stats():
    """Get current database statistics."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Get match counts
        cursor.execute("""
            SELECT match_status, COUNT(*) 
            FROM splink_data.customer_matches 
            GROUP BY match_status
        """)
        match_counts = dict(cursor.fetchall())
        
        # Get review queue stats
        cursor.execute("""
            SELECT status, COUNT(*) 
            FROM splink_data.review_queue 
            GROUP BY status
        """)
        review_counts = dict(cursor.fetchall())
        
        # Get model metadata
        cursor.execute("""
            SELECT model_version, trained_at, recall_score, precision_score, f1_score
            FROM splink_data.model_metadata
            ORDER BY trained_at DESC
            LIMIT 1
        """)
        model_info = cursor.fetchone()
        
        cursor.close()
    
    return {
        "matches": match_counts.get("MATCH", 0),
        "review": match_counts.get("REVIEW", 0),
        "non_matches": match_counts.get("NON_MATCH", 0),
        "review_pending": review_counts.get("pending", 0),
        "review_in_progress": review_counts.get("in_review", 0),
        "review_completed": review_counts.get("completed", 0),
        "model_version": model_info[0] if model_info else None,
        "model_trained_at": model_info[1].isoformat() if model_info else None,
        "recall": model_info[2] if model_info else None,
        "precision": model_info[3] if model_info else None,
        "f1": model_info[4] if model_info else None,
    }


def check_alerts(stats):
    """Check for alert conditions."""
    alerts = []
    
    # Alert if review queue is too large
    if stats["review_pending"] > 10000:
        alerts.append({
            "severity": "warning",
            "message": f"Review queue backlog: {stats['review_pending']} pending reviews"
        })
    
    # Alert if recall is too low
    if stats["recall"] is not None and stats["recall"] < 0.95:
        alerts.append({
            "severity": "critical",
            "message": f"Model recall {stats['recall']:.4f} below threshold 0.95"
        })
    
    # Alert if precision is too low
    if stats["precision"] is not None and stats["precision"] < 0.90:
        alerts.append({
            "severity": "warning",
            "message": f"Model precision {stats['precision']:.4f} below threshold 0.90"
        })
    
    return alerts


def send_alert(alerts):
    """Send alerts to monitoring system (Slack, Email, etc.)."""
    for alert in alerts:
        severity = alert.get("severity", "info")
        message = alert.get("message", "")
        
        # Log to console
        print(f"[{severity.upper()}] {message}")
        
        # TODO: Add Slack/Email integration
        # if severity == "critical":
        #     slack_webhook = os.environ.get("SLACK_WEBHOOK")
        #     if slack_webhook:
        #         requests.post(slack_webhook, json={"text": message})


def collect_metrics():
    """Collect and save metrics."""
    stats = get_db_stats()
    alerts = check_alerts(stats)
    
    # Send alerts
    send_alert(alerts)
    
    metrics = {
        "timestamp": datetime.utcnow().isoformat(),
        "stats": stats,
        "alerts": alerts
    }
    
    # Save to file
    with open(METRICS_FILE, "w") as f:
        json.dump(metrics, f, indent=2)
    
    return metrics


if __name__ == "__main__":
    metrics = collect_metrics()
    print(json.dumps(metrics, indent=2))