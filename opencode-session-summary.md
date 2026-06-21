# Session 2026-06-21

## Summary
Migrated auth rate limiting from in-memory dicts + threading locks to DB-backed `rate_limits` table.

## Changes
- `clinic_app/routes/auth.py`: Replaced `_LOGIN_RATE_LIMIT_BUCKETS`, `_PASSWORD_RESET_RATE_LIMIT_BUCKETS`, and their locks with DB queries using new helper functions (`_prune_rate_limits`, `_count_rate_limits`, `_record_rate_limit`)
- Replaced `_LOGIN_RATE_LIMIT_LOCK`, `_PASSWORD_RESET_RATE_LIMIT_LOCK`, `_REGISTER_RATE_LIMIT_LOCK`, `_PASSWORD_RESET_CLEANUP_LOCK` with DB-backed approach
- Replaced `_PASSWORD_RESET_LAST_CLEANUP_TS` global with direct DB cleanup
- Fixed `_record_login_failure` return value (was always `(False, None)`, now returns `(True, retry_after)` on lockout)
- Added default rate limit constants (`_LOGIN_RATE_LIMIT_MAX`, `_LOGIN_RATE_LIMIT_WINDOW`, `_LOGIN_RATE_LIMIT_LOCKOUT`, etc.)
- Kept empty `_LOGIN_RATE_LIMIT_BUCKETS`, `_PASSWORD_RESET_RATE_LIMIT_BUCKETS`, `_REGISTER_RATE_LIMIT_BUCKETS` dicts for test compatibility

## Bug Fixed
`_record_login_failure` always returned `(False, None)` instead of `(True, retry_after)` when lockout was triggered, causing the "Too many failed login attempts" flash message to never appear on the same request.

## Tests
- `tests.test_security`: 37/37 pass
- `tests.test_google_oauth`: 28/28 pass
