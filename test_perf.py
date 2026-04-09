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
