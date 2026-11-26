"Database operations for API"
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from dotenv import load_dotenv
from pathlib import Path
from urllib.parse import urlsplit

# Load .env file (force reload)
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.environ.get("POSTGRES_PORT", "5432")
POSTGRES_DB = os.environ.get("POSTGRES_DB", "crm")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "crm_user")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD")


@contextmanager
def get_connection():
    if not POSTGRES_PASSWORD:
        raise RuntimeError("POSTGRES_PASSWORD belum diset untuk koneksi PostgreSQL lokal")
    url = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    conn = psycopg2.connect(url)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_supabase_connection():
    url = os.getenv("SUPABASE_DATABASE_URL")
    password = os.getenv("PASSWORD_SUPABASE")

    if not url:
        raise RuntimeError("SUPABASE_DATABASE_URL belum diset")

    # Jika url tidak punya postgresql:// prefix
    if not url.startswith("postgres"):
        url = f"postgresql://postgres:{password}@{url}"

    conn = psycopg2.connect(
        url,
        sslmode="require",
        connect_timeout=10,
    )

    try:
        yield conn
    finally:
        conn.close()

@contextmanager
def get_cursor():
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
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT match_status, COUNT(*) as count
                FROM splink_data.customer_matches
                GROUP BY match_status
            """)
            return dict(cursor.fetchall())


def get_review_queue_stats():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM splink_data.review_queue
                GROUP BY status
            """)
            return dict(cursor.fetchall())
