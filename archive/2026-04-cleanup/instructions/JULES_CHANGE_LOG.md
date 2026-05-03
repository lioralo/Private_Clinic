## Change Log

### April 9, 2026 - Add Unit Tests for Session Inactivity Timeout
* **Time:** 08:08 UTC
* **Summary:** Added unit tests to `test_security.py` to cover the `enforce_inactivity_timeout` logic in `app.py`. Covered scenarios include updating `last_activity_at`, logging out on timeout, ignoring static files, and handling unauthenticated users. Fixed a minor mismatch in `request context` usage for session validation.

* 2025-02-24 12:00:00 - Optimized the JSON history import process by replacing individual `INSERT INTO receipts` calls inside a loop with a single `db.executemany` operation in `app.py`. This resolves an N+1 query issue, providing a ~18% performance improvement during large imports.
* 2026-04-09 08:08:48: Optimized bulk appointment updates by using `db.executemany` instead of `db.execute` inside a loop in `app.py`, mitigating N+1 query overhead.
