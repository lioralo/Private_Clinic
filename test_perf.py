import time
import app as app_module
from app import init_db, get_db
from flask import Flask
import tempfile
import json
import sqlite3

app = app_module.app

with app.app_context():
    # Setup test DB
    db_fd, app.config['DATABASE'] = tempfile.mkstemp()
    init_db()
    db = get_db()

    # Create patient
    cursor = db.execute("INSERT INTO patients (name, email, status) VALUES ('Test', 'test@example.com', 'candidate')")
    patient_id = cursor.lastrowid
    db.commit()

    # Create test data
    receipts_data = []
    for i in range(100000):
        receipts_data.append({
            'amount': 100,
            'description': f'Test receipt {i}',
            'created_at': '2023-01-01 12:00:00'
        })

    start = time.perf_counter()
    receipts_added = 0
    for receipt in receipts_data:
        db.execute('''INSERT INTO receipts
            (patient_id, amount, description, created_at)
            VALUES (?, ?, ?, ?)''',
            (patient_id, receipt.get('amount'), receipt.get('description'), receipt.get('created_at')))
        receipts_added += 1
    db.commit()
    end = time.perf_counter()

    print(f"Time to insert 100000 receipts (unoptimized): {end - start:.5f}s")

    # Measure optimized
    start = time.perf_counter()
    receipts_added = 0
    if receipts_data:
        receipt_tuples = [
            (patient_id, r.get('amount'), r.get('description'), r.get('created_at'))
            for r in receipts_data
        ]
        db.executemany('''INSERT INTO receipts
            (patient_id, amount, description, created_at)
            VALUES (?, ?, ?, ?)''', receipt_tuples)
        receipts_added += len(receipts_data)
    db.commit()
    end = time.perf_counter()

    print(f"Time to insert 100000 receipts (optimized): {end - start:.5f}s")
import sqlite3
import random

def test_loop(conn, rows, group_id):
    start = time.time()
    for row in rows:
        conn.execute('UPDATE appointments SET recurrence_group_id = ? WHERE id = ?', (group_id, row['id']))
    return time.time() - start

def test_executemany(conn, rows, group_id):
    start = time.time()
    update_data = [(group_id, row['id']) for row in rows]
    conn.executemany('UPDATE appointments SET recurrence_group_id = ? WHERE id = ?', update_data)
    return time.time() - start

if __name__ == '__main__':
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE appointments (id INTEGER PRIMARY KEY, recurrence_group_id TEXT);')
    num_rows = 1000
    for i in range(num_rows):
        conn.execute('INSERT INTO appointments (id) VALUES (?)', (i,))
    conn.commit()

    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT id FROM appointments').fetchall()

    group_id = 'test_group'

    t_loop = test_loop(conn, rows, group_id)
    t_executemany = test_executemany(conn, rows, group_id)

    print(f"Loop time: {t_loop:.6f}s")
    print(f"Executemany time: {t_executemany:.6f}s")
    if t_loop > 0:
        print(f"Improvement: {(t_loop - t_executemany) / t_loop * 100:.2f}%")
