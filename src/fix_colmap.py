#!/usr/bin/env python3
import re

path = r'C:\Users\User\Downloads\dedup-system-splink\src\config.py'
with open(path, 'r') as f:
    content = f.read()

old = 'DB_COLUMN_MAP: dict[str, str] = {}'
new = 'DB_COLUMN_MAP: dict[str, str] = {"client_id": "source_id", "cust_id": "source_id"}'

if old in content:
    content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)
    print("SUCCESS: DB_COLUMN_MAP updated")
else:
    print("NOT FOUND - checking current content...")
    # Show what's around DB_COLUMN_MAP
    m = re.search(r'DB_COLUMN_MAP.*?', content)
    if m:
        print(m.group()[:200])