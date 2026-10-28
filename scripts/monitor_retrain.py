"""Monitor and trigger retraining when metrics degrade."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from monitor.metrics import collect_metrics


def check_retrain_needed(metrics):
    """Check if retraining is needed based on metrics."""
    alerts = metrics.get("alerts", [])
    
    # Check for critical alerts
    critical_alerts = [a for a in alerts if a["severity"] == "critical"]
    if critical_alerts:
        return True, f"Critical alerts: {[a['message'] for a in critical_alerts]}"
    
    # Check if review queue is too large
    stats = metrics.get("stats", {})
    if stats.get("review_pending", 0) > 50000:
        return True, f"Review queue backlog: {stats['review_pending']} pending"
    
    return False, "No retraining needed"


def trigger_retrain():
    """Trigger model retraining."""
    print("Triggering model retraining...")
    # TODO: Implement actual retraining logic
    # This could call src.splink_model.train_model() or similar
    print("Retraining triggered (implement actual logic)")


def main():
    print("Checking metrics and retraining status...")
    metrics = collect_metrics()
    
    needed, reason = check_retrain_needed(metrics)
    print(f"Retrain needed: {needed}")
    print(f"Reason: {reason}")
    
    if needed:
        trigger_retrain()
    
    # Print current stats
    stats = metrics.get("stats", {})
    print(f"\nCurrent Stats:")
    print(f"  Matches: {stats.get('matches', 0):,}")
    print(f"  Review: {stats.get('review', 0):,}")
    print(f"  Non-matches: {stats.get('non_matches', 0):,}")
    print(f"  Review pending: {stats.get('review_pending', 0):,}")
    print(f"  Model version: {stats.get('model_version', 'N/A')}")
    print(f"  Recall: {stats.get('recall', 'N/A')}")
    print(f"  Precision: {stats.get('precision', 'N/A')}")
    print(f"  F1: {stats.get('f1', 'N/A')}")


if __name__ == "__main__":
    main()