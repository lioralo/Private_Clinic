import time
import sqlite3
import os
from app import init_db, get_db, app

def setup_db(num_notifications):
    if os.path.exists('test_benchmark.db'):
        os.remove('test_benchmark.db')

    conn = sqlite3.connect('test_benchmark.db')
    conn.execute('''
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('PRAGMA synchronous = OFF') # speed up inserts
    conn.execute('PRAGMA journal_mode = MEMORY')

    # Insert test data
    notifications_data = [('Test message ' + str(i), 0) for i in range(num_notifications)]
    conn.executemany('INSERT INTO notifications (message, is_read) VALUES (?, ?)', notifications_data)
    conn.commit()
    return conn

def test_n_plus_1(conn):
    start_time = time.time()

    notifications = conn.execute('SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at ASC').fetchall()

    for n in notifications:
        conn.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (n[0],))
    conn.commit()

    end_time = time.time()
    return end_time - start_time

def test_optimized(conn):
    start_time = time.time()

    notifications = conn.execute('SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at ASC').fetchall()

    if notifications:
        notification_ids = [n[0] for n in notifications]
        placeholders = ','.join(['?'] * len(notification_ids))
        conn.execute(f'UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders})', notification_ids)
        conn.commit()

    end_time = time.time()
    return end_time - start_time

if __name__ == '__main__':
    # Test with 1000 notifications
    conn = setup_db(1000)
    time_n_plus_1 = test_n_plus_1(conn)
    conn.close()

    conn = setup_db(1000)
    time_optimized = test_optimized(conn)
    conn.close()

    print(f"N+1 Approach (1000 rows): {time_n_plus_1:.4f} seconds")
    print(f"Optimized Approach (1000 rows): {time_optimized:.4f} seconds")
    print(f"Improvement: {time_n_plus_1 / time_optimized:.2f}x faster")
