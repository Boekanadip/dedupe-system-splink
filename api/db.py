"""Database operations for API."""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from dotenv import load_dotenv
from pathlib import Path

# Load .env file
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "crm")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "crm_user")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "crm_password_2026")

DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

@contextmanager
def get_connection():
    """Get database connection with context manager."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

@contextmanager
def get_cursor():
    """Get cursor with context manager."""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


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
