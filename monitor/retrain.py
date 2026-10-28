"""Retrain trigger and scheduler for CRM entity resolution."""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.db import get_cursor
from monitor.metrics import check_model_stale, check_review_backlog

def should_retrain(auto_threshold=True):
    """Check if model should be retrained."""
    reasons = []
    
    # Check model age
    stale = check_model_stale(days_threshold=7)
    if stale.get('stale'):
        reasons.append(f"Model stale: {stale['days_since_train']} days since training")
    
    # Check review backlog
    backlog = check_review_backlog(threshold=1000)
    if backlog.get('backlog'):
        reasons.append(f"Review backlog: {backlog['pending_count']} pending reviews")
    
    # Check for new gold labels
    try:
        with get_cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as cnt 
                FROM splink_data.gold_labels 
                WHERE created_at > (
                    SELECT MAX(trained_at) FROM splink_data.model_metadata
                )
            """)
            new_labels = cursor.fetchone()['cnt']
            if new_labels > 100:
                reasons.append(f"New gold labels: {new_labels} since last training")
    except:
        pass
    
    return {
        "should_retrain": len(reasons) > 0 if auto_threshold else True,
        "reasons": reasons,
        "timestamp": datetime.utcnow().isoformat()
    }

def trigger_retrain():
    """Trigger model retraining (placeholder)."""
    print("=" * 50)
    print("RETRAIN TRIGGERED")
    print("=" * 50)
    
    # This would call the actual training
    # from src.splink_model import train_model
    # train_model(customers_df)
    
    print("Note: Implement actual retrain call in src/splink_model.py")
    print("=" * 50)

def schedule_retrain():
    """Check schedule and trigger retrain if needed."""
    result = should_retrain(auto_threshold=True)
    
    print(f"Retrain check: {result['timestamp']}")
    print(f"Should retrain: {result['should_retrain']}")
    
    if result['reasons']:
        print("Reasons:")
        for r in result['reasons']:
            print(f"  - {r}")
    
    if result['should_retrain']:
        trigger_retrain()
    
    return result

if __name__ == "__main__":
    schedule_retrain()