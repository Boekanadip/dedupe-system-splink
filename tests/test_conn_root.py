from api.db import get_supabase_connection

with get_supabase_connection() as conn:
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM public.customers")
        print(cursor.fetchone())