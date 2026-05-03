import sqlite3
import time
from datetime import datetime, timedelta
import statistics

def setup_db(db_name="perf_test.db", num_rows=1000):
    conn = sqlite3.connect(db_name)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_date TEXT,
            appointment_time TEXT,
            duration_minutes INTEGER,
            meeting_type TEXT,
            meeting_link TEXT,
            meeting_platform TEXT,
            meeting_title TEXT,
            save_to_google INTEGER,
            recurrence_days TEXT
        )
    ''')
    conn.execute('DELETE FROM appointments')

    data = []
    base_date = datetime(2025, 1, 1)
    for i in range(num_rows):
        data.append((
            (base_date + timedelta(days=i)).isoformat(),
            '10:00',
            60,
            'online',
            'link',
            'zoom',
            'title',
            1,
            '1'
        ))

    conn.executemany('''
        INSERT INTO appointments (
            appointment_date, appointment_time, duration_minutes,
            meeting_type, meeting_link, meeting_platform,
            meeting_title, save_to_google, recurrence_days
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', data)
    conn.commit()
    return conn

def test_loop_execute(conn):
    cursor = conn.cursor()

    # Simulate the loop to collect data
    cursor.execute("SELECT id, appointment_date FROM appointments")
    rows = cursor.fetchall()

    start_time = time.time()
    for row in rows:
        row_id, date_str = row
        new_date = (datetime.fromisoformat(date_str) + timedelta(days=1)).isoformat()
        cursor.execute('''
            UPDATE appointments
            SET appointment_date = ?, appointment_time = ?, duration_minutes = ?,
                meeting_type = ?, meeting_link = ?, meeting_platform = ?,
                meeting_title = ?, save_to_google = ?, recurrence_days = ?
            WHERE id = ?
        ''', (new_date, '11:00', 45, 'in_person', None, None, None, 0, '2', row_id))

    conn.commit()
    return time.time() - start_time

def test_executemany(conn):
    cursor = conn.cursor()

    # Simulate the loop to collect data
    cursor.execute("SELECT id, appointment_date FROM appointments")
    rows = cursor.fetchall()

    update_data = []
    for row in rows:
        row_id, date_str = row
        new_date = (datetime.fromisoformat(date_str) + timedelta(days=1)).isoformat()
        update_data.append((
            new_date, '11:00', 45, 'in_person', None, None, None, 0, '2', row_id
        ))

    start_time = time.time()
    if update_data:
        cursor.executemany('''
            UPDATE appointments
            SET appointment_date = ?, appointment_time = ?, duration_minutes = ?,
                meeting_type = ?, meeting_link = ?, meeting_platform = ?,
                meeting_title = ?, save_to_google = ?, recurrence_days = ?
            WHERE id = ?
        ''', update_data)

    conn.commit()
    return time.time() - start_time

if __name__ == '__main__':
    num_rows = 10000

    loop_times = []
    execmany_times = []

    for _ in range(5):
        conn1 = setup_db("perf_test1.db", num_rows)
        loop_times.append(test_loop_execute(conn1))

        conn2 = setup_db("perf_test2.db", num_rows)
        execmany_times.append(test_executemany(conn2))

    avg_loop = statistics.mean(loop_times)
    avg_execmany = statistics.mean(execmany_times)

    print(f"Average Loop execute: {avg_loop:.4f} seconds")
    print(f"Average Executemany: {avg_execmany:.4f} seconds")
    print(f"Improvement: {avg_loop/avg_execmany:.2f}x faster")
