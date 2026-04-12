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
from app import app, get_db, build_week_calendar_snapshot
from datetime import datetime
import json
import sqlite3

class MockUser:
    def __init__(self):
        self.role = 'admin'
        self.patient_id = None

with app.app_context():
    db = get_db()

    # We need patients with status 'candidate' and past appointments.
    today = datetime.now().date().isoformat()
    for i in range(10000):
        db.execute("INSERT INTO patients (id, name, status, can_self_schedule) VALUES (?, ?, 'candidate', 0)", (i, f'Patient {i}'))
        db.execute("INSERT INTO appointments (patient_id, appointment_date, appointment_time, is_recurring, status) VALUES (?, '2020-01-01', '10:00', 0, 'scheduled')", (i,))
        # About half of them have future appointments
        if i % 2 == 0:
            db.execute("INSERT INTO appointments (patient_id, appointment_date, appointment_time, is_recurring, status) VALUES (?, '2030-01-01', '10:00', 0, 'scheduled')", (i,))
    db.commit()

    week_start = datetime.now().date()
    user = MockUser()

    # warm up cache
    build_week_calendar_snapshot(db, week_start, user)

    start_time = time.time()
    snapshot = build_week_calendar_snapshot(db, week_start, user)
    end_time = time.time()

    print(f"Time taken: {end_time - start_time} seconds")
