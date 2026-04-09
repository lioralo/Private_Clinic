* 2026-04-09 08:08:48: Optimized bulk appointment updates by using `db.executemany` instead of `db.execute` inside a loop in `app.py`, mitigating N+1 query overhead.
