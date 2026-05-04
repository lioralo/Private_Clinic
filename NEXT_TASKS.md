# Next Implementation Tasks (WIP)

Status: planned and not merged.

1. Security and Reliability
- Add SMTP dry-run check from CLI script for deployment validation.
- Add admin lockout event notifications (optional email to security inbox).
- Add forced logout of all sessions after authenticator disable.
- Add reset-token entropy/length assertion and metrics logging.

2. Observability
- Add a small security dashboard widget: failed logins in last 24h, resets requested, resets completed.
- Add structured security logs for auth_* events with request IP and user-agent hashes.
- Add retention cleanup telemetry counts (rows deleted per run).

3. Usability
- Add dedicated admin settings page for SMTP configuration test guidance.
- Add password policy helper text to reset page with live checks.
- Add one-click copy-safe export of recent auth events for incident review.

4. Data Protection
- Add optional hashing/redaction of audit details fields.
- Add configurable retention for notifications and messages.
- Add automatic purge for stale, unverified candidates after configurable time.

5. Testing
- Add focused tests for SMTP test endpoint success/failure with monkeypatched sender.
- Add tests for retention cleanup guard (deletes old rows, preserves recent rows).
- Add tests for session invalidation after admin password change and reset.
