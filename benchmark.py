import time
import sqlite3
import json

def create_db():
    conn = sqlite3.connect(':memory:')
    conn.execute('''CREATE TABLE receipts (
        id INTEGER PRIMARY KEY,
        patient_id INTEGER,
        amount REAL,
        description TEXT,
        created_at TEXT
    )''')
    return conn

def run_unoptimized(conn, data, patient_id):
    receipts_added = 0
    start = time.perf_counter()
    for receipt in data.get('receipts', []):
        conn.execute('''INSERT INTO receipts
            (patient_id, amount, description, created_at)
            VALUES (?, ?, ?, ?)''',
            (patient_id, receipt.get('amount'), receipt.get('description'), receipt.get('created_at')))
        receipts_added += 1
    end = time.perf_counter()
    return end - start, receipts_added

def run_optimized(conn, data, patient_id):
    receipts_added = 0
    start = time.perf_counter()
    receipts = data.get('receipts', [])
    if receipts:
        receipt_data = [
            (patient_id, receipt.get('amount'), receipt.get('description'), receipt.get('created_at'))
            for receipt in receipts
        ]
        conn.executemany('''INSERT INTO receipts
            (patient_id, amount, description, created_at)
            VALUES (?, ?, ?, ?)''', receipt_data)
        receipts_added += len(receipts)
    end = time.perf_counter()
    return end - start, receipts_added

data = {'receipts': [{'amount': 100, 'description': 'desc', 'created_at': '2023-01-01'} for _ in range(10000)]}

conn1 = create_db()
time_unopt, _ = run_unoptimized(conn1, data, 1)

conn2 = create_db()
time_opt, _ = run_optimized(conn2, data, 1)

print(f"Unoptimized: {time_unopt:.5f}s")
print(f"Optimized:   {time_opt:.5f}s")
print(f"Improvement: {time_unopt / time_opt:.2f}x")
