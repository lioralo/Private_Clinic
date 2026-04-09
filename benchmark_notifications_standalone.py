import time
import sqlite3
import os

def setup_db(num_notifications):
    if os.path.exists('test_benchmark.db'):
        os.remove('test_benchmark.db')

    conn = sqlite3.connect('test_benchmark.db')
    conn.row_factory = sqlite3.Row
    conn.execute('''
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Insert test data
    notifications_data = [('Test message ' + str(i), 0) for i in range(num_notifications)]
    conn.executemany('INSERT INTO notifications (message, is_read) VALUES (?, ?)', notifications_data)
    conn.commit()
    return conn

def test_n_plus_1(conn):
    start_time = time.time()

    notifications = conn.execute('SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at ASC').fetchall()

    for n in notifications:
        conn.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (n['id'],))
    conn.commit()

    end_time = time.time()
    return end_time - start_time

def test_optimized_in(conn):
    start_time = time.time()

    notifications = conn.execute('SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at ASC').fetchall()

    if notifications:
        notification_ids = [n['id'] for n in notifications]
        placeholders = ','.join(['?'] * len(notification_ids))
        conn.execute(f'UPDATE notifications SET is_read = 1 WHERE id IN ({placeholders})', notification_ids)
        conn.commit()

    end_time = time.time()
    return end_time - start_time

if __name__ == '__main__':
    NUM_ROWS = 10000

    conn = setup_db(NUM_ROWS)
    time_n_plus_1 = test_n_plus_1(conn)
    conn.close()

    conn = setup_db(NUM_ROWS)
    time_optimized_in = test_optimized_in(conn)
    conn.close()

    print(f"N+1 Approach ({NUM_ROWS} rows): {time_n_plus_1:.4f} seconds")
    print(f"Optimized IN clause Approach ({NUM_ROWS} rows): {time_optimized_in:.4f} seconds")
    print(f"Improvement: {time_n_plus_1 / time_optimized_in:.2f}x faster")
