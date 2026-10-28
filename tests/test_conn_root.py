from api.db import get_cursor

with get_cursor() as cursor:
    cursor.execute("SELECT COUNT(*) FROM splink_data.customers")
    print(cursor.fetchone())