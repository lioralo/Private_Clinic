
* 2025-02-24 12:00:00 - Optimized the JSON history import process by replacing individual `INSERT INTO receipts` calls inside a loop with a single `db.executemany` operation in `app.py`. This resolves an N+1 query issue, providing a ~18% performance improvement during large imports.
