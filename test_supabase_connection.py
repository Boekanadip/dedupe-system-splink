from api.db import get_supabase_connection

with get_supabase_connection() as conn:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT current_database(), current_schema()
        """)
        print(cursor.fetchone())

        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        print(cursor.fetchall())