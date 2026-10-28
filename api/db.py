"""Database operations for API."""
from src.db import get_connection, get_cursor

def get_match_stats():
    """Get match statistics from database."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT match_status, COUNT(*) as count
                FROM splink_data.customer_matches
                GROUP BY match_status
            """)
            return dict(cursor.fetchall())

def get_review_queue_stats():
    """Get review queue statistics."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM splink_data.review_queue
                GROUP BY status
            """)
            return dict(cursor.fetchall())