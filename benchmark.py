import time
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
