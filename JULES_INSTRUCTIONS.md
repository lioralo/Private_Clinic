## Change Log

### April 9, 2026 - Add Unit Tests for Session Inactivity Timeout
* **Time:** 08:08 UTC
* **Summary:** Added unit tests to `test_security.py` to cover the `enforce_inactivity_timeout` logic in `app.py`. Covered scenarios include updating `last_activity_at`, logging out on timeout, ignoring static files, and handling unauthenticated users. Fixed a minor mismatch in `request context` usage for session validation.
