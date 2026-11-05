"""Auto-retrain logic: monitor metrics dan trigger retrain."""
import sys
from pathlib import Path
import subprocess

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from datetime import datetime, timedelta
from src.db import get_connection
from psycopg2.extras import execute_values


def get_gold_label_count() -> int:
    with get_connection() as conn:
        result = pd.read_sql("SELECT COUNT(*) as count FROM splink_data.gold_labels", conn)
    return int(result['count'].iloc[0]) if not result.empty else 0


def get_last_training_date() -> datetime | None:
    with get_connection() as conn:
        result = pd.read_sql(
            "SELECT MAX(trained_at) as last_trained FROM splink_data.model_metadata", conn
        )
    if result.empty or pd.isna(result['last_trained'].iloc[0]):
        return None
    return pd.to_datetime(result['last_trained'].iloc[0])


def get_latest_metrics() -> dict:
    with get_connection() as conn:
        result = pd.read_sql("""
            SELECT precision_score, recall_score, f1_score 
            FROM splink_data.model_metadata 
            ORDER BY trained_at DESC LIMIT 1
        """, conn)
    if result.empty or pd.isna(result['precision_score'].iloc[0]):
        return {'precision': None, 'recall': None, 'f1': None}
    return {
        'precision': float(result['precision_score'].iloc[0]),
        'recall': float(result['recall_score'].iloc[0]),
        'f1': float(result['f1_score'].iloc[0])
    }


def should_retrain(
    min_new_labels: int = 100,
    min_days_since_last_train: int = 7,
    precision_threshold: float = 0.7
) -> dict:
    reasons = []
    metrics = {}
    
    gold_count = get_gold_label_count()
    metrics['gold_labels'] = gold_count
    if gold_count >= min_new_labels:
        reasons.append(f"Gold labels: {gold_count} (>= {min_new_labels})")
    
    last_train = get_last_training_date()
    if last_train:
        days_since = (datetime.now() - last_train).days
        metrics['days_since_last_train'] = days_since
        if days_since >= min_days_since_last_train:
            reasons.append(f"Days since last train: {days_since} (>= {min_days_since_last_train})")
    else:
        reasons.append("No previous training found")
        metrics['days_since_last_train'] = None
    
    latest = get_latest_metrics()
    metrics.update(latest)
    if latest['precision'] is not None and latest['precision'] < precision_threshold:
        reasons.append(f"Precision: {latest['precision']:.2%} (< {precision_threshold:.0%})")
    
    return {
        'should_retrain': len(reasons) > 0,
        'reasons': reasons,
        'metrics': metrics,
        'timestamp': datetime.now().isoformat()
    }


def run_training(columns: list = None) -> bool:
    """Jalankan training Splink."""
    cmd = [sys.executable, "-m", "src.splink_model", "--sample"]
    if columns:
        cmd.extend(["--columns", ",".join(columns)])
    print(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print("[OK] Training completed")
            return True
        else:
            print(f"[ERROR] Training failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("[ERROR] Training timed out")
        return False
    except Exception as e:
        print(f"[ERROR] Training error: {e}")
        return False


def save_model_metrics(success: bool, runtime: float, error: str = None):
    """Simpan metrics setelah training."""
    import json
    from src.model_lifecycle import latest
    from src.config import MATCH_THRESHOLD, REVIEW_THRESHOLD
    
    version = latest()
    if not version:
        print("[WARN] No model version found to log metrics")
        return
    
    metrics = {
        'model_version': version.name,
        'trained_at': datetime.now().isoformat(),
        'training_success': success,
        'runtime_seconds': runtime,
        'error_message': error,
        'threshold_match': MATCH_THRESHOLD,
        'threshold_review': REVIEW_THRESHOLD,
    }
    
    with get_connection() as conn:
        with conn.cursor() as cursor:
            execute_values(cursor, """
                INSERT INTO splink_data.model_metadata 
                (model_version, trained_at, precision_score, recall_score, f1_score, threshold_match, threshold_non_match, training_data_size, notes)
                VALUES %s
            """, [(
                version.name,
                datetime.now(),
                None, None, None,
                MATCH_THRESHOLD, REVIEW_THRESHOLD,
                None,
                json.dumps(metrics)
            )])
            conn.commit()
    print(f"[OK] Model metrics saved: {version.name}")


def trigger_retrain(columns: list = None) -> bool:
    print("\n[ACTION] Starting auto-retrain...")
    start = datetime.now()
    success = run_training(columns)
    runtime = (datetime.now() - start).total_seconds()
    save_model_metrics(success, runtime, None if success else "Training failed")
    return success


def main():
    print("=" * 60)
    print("Auto-Retrain Logic")
    print("=" * 60)
    
    result = should_retrain()
    print(f"\nShould retrain: {result['should_retrain']}")
    print(f"Metrics: {result['metrics']}")
    
    if result['reasons']:
        print("\nReasons:")
        for reason in result['reasons']:
            print(f"  • {reason}")
        
        # Auto-trigger retrain
        trigger_retrain(columns=['first_name_std', 'last_name_std', 'email_std', 'phone_std', 'city_std'])
    else:
        print("\n[OK] No retrain needed")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()