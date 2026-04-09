import time
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
