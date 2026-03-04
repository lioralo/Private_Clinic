import sqlite3
import os
import sys

db_path = 'clinic.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cur.fetchall()
    print("Tables:", tables)
    for table in tables:
        cur.execute(f"PRAGMA table_info({table[0]})")
        print(f"Schema for {table[0]}:", cur.fetchall())
else:
    print("No clinic.db yet")
