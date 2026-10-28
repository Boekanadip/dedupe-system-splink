from api.db import get_cursor, get_connection

# Migrate data from customers_v2 to splink_data.customers
print("Migrating customers_v2 to splink_data.customers...")

with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO splink_data.customers (
            customer_id, first_name, last_name, email, phone,
            address, city, state, dob
        )
        SELECT 
            customer_id, first_name, last_name, email, phone_number,
            address, city, state, dob::date
        FROM customers_v2
        ON CONFLICT (customer_id) DO NOTHING
    """)
    conn.commit()
    
    cursor.execute("SELECT COUNT(*) FROM splink_data.customers")
    count = cursor.fetchone()[0]
    print(f"Inserted {count} customers")
    cursor.close()

print("Done!")