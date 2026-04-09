import time
import sqlite3
from datetime import datetime, timedelta

def setup_db(db):
    db.execute('''CREATE TABLE IF NOT EXISTS blocked_slots (
        id INTEGER PRIMARY KEY, blocked_date TEXT, blocked_time TEXT, duration_minutes INTEGER,
        title TEXT, is_private INTEGER, block_type TEXT, created_by INTEGER
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS slots_override (
        id INTEGER PRIMARY KEY, slot_date TEXT, slot_time TEXT, status TEXT, booked_by_name TEXT, booked_at TEXT
    )''')
    db.commit()

def test_original(db, dates_to_create, parsed_start, duration_value, title, is_private, block_type, current_user_id):
    start_time = time.time()
    for block_day in dates_to_create:
        db.execute('''
            INSERT INTO blocked_slots
            (blocked_date, blocked_time, duration_minutes, title, is_private, block_type, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (block_day.isoformat(), parsed_start.strftime('%H:%M'), duration_value, title or None, is_private, block_type, current_user_id))
        db.execute('''
            UPDATE slots_override
            SET status = 'booked', booked_by_name = ?, booked_at = ?
            WHERE slot_date = ? AND slot_time = ? AND status = 'available'
        ''', (
            title or 'Blocked Slot',
            datetime.now().isoformat(),
            block_day.isoformat(),
            parsed_start.strftime('%H:%M')
        ))
    db.commit()
    return time.time() - start_time

def test_optimized(db, dates_to_create, parsed_start, duration_value, title, is_private, block_type, current_user_id):
    start_time = time.time()
    if dates_to_create:
        now_iso = datetime.now().isoformat()
        blocked_slots_data = [
            (block_day.isoformat(), parsed_start.strftime('%H:%M'), duration_value, title or None, is_private, block_type, current_user_id)
            for block_day in dates_to_create
        ]
        slots_override_data = [
            (title or 'Blocked Slot', now_iso, block_day.isoformat(), parsed_start.strftime('%H:%M'))
            for block_day in dates_to_create
        ]

        db.executemany('''
            INSERT INTO blocked_slots
            (blocked_date, blocked_time, duration_minutes, title, is_private, block_type, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', blocked_slots_data)

        db.executemany('''
            UPDATE slots_override
            SET status = 'booked', booked_by_name = ?, booked_at = ?
            WHERE slot_date = ? AND slot_time = ? AND status = 'available'
        ''', slots_override_data)
    db.commit()
    return time.time() - start_time

if __name__ == "__main__":
    db = sqlite3.connect(':memory:')
    setup_db(db)

    dates_to_create = [datetime.now() + timedelta(days=i) for i in range(1000)]
    parsed_start = datetime.now()

    orig_time = test_original(db, dates_to_create, parsed_start, 60, "Test", 1, "blocked", 1)

    db.execute('DELETE FROM blocked_slots')
    db.execute('DELETE FROM slots_override')
    db.commit()

    opt_time = test_optimized(db, dates_to_create, parsed_start, 60, "Test", 1, "blocked", 1)

    print(f"Original: {orig_time:.4f}s")
    print(f"Optimized: {opt_time:.4f}s")
    if orig_time > 0:
        print(f"Improvement: {(orig_time - opt_time) / orig_time * 100:.2f}%")
