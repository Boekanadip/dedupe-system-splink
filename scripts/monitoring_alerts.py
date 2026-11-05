"""Monitoring alerts untuk production."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from datetime import datetime
from src.db import get_connection


def check_match_rate_anomaly(threshold_low: float = 0.005, threshold_high: float = 0.05) -> dict:
    """Cek anomali match rate."""
    with get_connection() as conn:
        df = pd.read_sql("""
            SELECT 
                match_status, 
                COUNT(*) as count 
            FROM splink_data.customer_matches 
            GROUP BY match_status
        """, conn)
    
    total = df['count'].sum()
    match_count = df[df['match_status'] == 'MATCH']['count'].iloc[0] if 'MATCH' in df['match_status'].values else 0
    match_rate = match_count / total if total > 0 else 0
    
    alert = None
    if match_rate < threshold_low:
        alert = f"⚠️ ALERT: Match rate terlalu rendah ({match_rate:.2%})"
    elif match_rate > threshold_high:
        alert = f"⚠️ ALERT: Match rate terlalu tinggi ({match_rate:.2%})"
    
    return {
        'metric': 'match_rate',
        'value': match_rate,
        'alert': alert,
        'timestamp': datetime.now().isoformat()
    }


def check_review_queue_size(threshold: int = 1000) -> dict:
    """Cek ukuran review queue."""
    with get_connection() as conn:
        result = pd.read_sql("SELECT COUNT(*) as count FROM splink_data.review_queue WHERE status = 'pending'", conn)
    
    count = result['count'].iloc[0]
    alert = None
    if count > threshold:
        alert = f"⚠️ ALERT: Review queue penuh ({count} pending)"
    
    return {
        'metric': 'review_queue_size',
        'value': count,
        'alert': alert,
        'timestamp': datetime.now().isoformat()
    }


def send_alert(message: str, channel: str = "console"):
    """Send alert ke channel (console/slack/email)."""
    if channel == "console":
        print(f"[ALERT] {message}")
    elif channel == "slack":
        # TODO: Implement Slack webhook
        print(f"[SLACK] Would send: {message}")
    elif channel == "email":
        # TODO: Implement email via SMTP
        print(f"[EMAIL] Would send: {message}")


def main():
    print("=" * 60)
    print("Monitoring Alerts")
    print("=" * 60)
    
    # Check metrics
    match_rate_result = check_match_rate_anomaly()
    review_queue_result = check_review_queue_size()
    
    # Print results
    print(f"\n[Metric] Match Rate: {match_rate_result['value']:.2%}")
    if match_rate_result['alert']:
        send_alert(match_rate_result['alert'])
    
    print(f"[Metric] Review Queue: {review_queue_result['value']} pending")
    if review_queue_result['alert']:
        send_alert(review_queue_result['alert'])
    
    # Summary
    alerts = [r for r in [match_rate_result, review_queue_result] if r['alert']]
    if alerts:
        print(f"\n[WARN] {len(alerts)} alert(s) detected")
    else:
        print("\n[OK] All metrics normal")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
