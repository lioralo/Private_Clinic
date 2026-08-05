# Security Review

Scope: application-level security of the Private Psychotherapy Clinic Management System (Flask + SQLite). This document inventories the existing controls, records the automated test results, lists the hardening applied in this change, and enumerates the deployment-sensitive recommendations that were intentionally *not* auto-applied.

## Automated test results

`python -m pytest tests/test_security.py` → **39 passed** (was 37 passing / 1 failing before this review).

- The previously-failing `test_login_rate_limit_resets_after_successful_login` was a **test/route drift** issue, not a security regression: the test used `GET /logout`, but `/logout` is now `POST`-only, so the session was never ended and the follow-up assertion ran against an authenticated page. Fixed the test to `POST /logout`. The rate-limit reset logic itself was already correct.
- Added `test_csrf_protection_active_but_webhook_is_exempt` to lock in the CSRF fix below.

## Control inventory (verified present)

| Area | Control | Location |
|------|---------|----------|
| Authentication | Flask-Login; Werkzeug password hashing; dummy-hash timing-attack mitigation for unknown users | `app.py`, `clinic_app/routes/auth.py`, `clinic_app/config.py` |
| 2FA | TOTP via `pyotp` (`valid_window=1`); hashed single-use recovery codes; 30-min TOTP re-auth window; admin (prod) required when configured | `app.py`, `clinic_app/routes/auth.py`, `clinic_app/routes/admin.py` |
| Sessions | `HttpOnly` + configurable `SameSite`; inactivity timeout (default 5 min); `session_version` invalidation on security changes; heartbeat endpoint | `app.py` (`enforce_inactivity_timeout`, `enforce_session_version_match`) |
| Authorization | Per-route `role`/ownership checks; patient-portal IDOR guards (assessments, receipts, files, goals, calendar) | `app.py`, `clinic_app/routes/*.py` |
| CSRF | `CSRFProtect(app)` global; `is_csrf_exempt` flag now honored (see fix below) | `app.py` |
| Rate limiting | DB-backed (`rate_limits`): login (5/300s + lockout), password reset, registration, public booking, contact-admin, and now public contact-inquiry | `clinic_app/routes/auth.py`, `clinic_app/utils.py`, `clinic_app/routes/messaging.py` |
| Security headers | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, CSP, and now HSTS over TLS | `app.py` (`apply_security_headers`) |
| Secrets/crypto | `SECRET_KEY` length enforced (≥32) in prod; Fernet-encrypted backups; hashed password-reset tokens | `app.py`, `clinic_app/backup.py` |
| Uploads | Extension allowlists (single source in `config.py`); `secure_filename`; 10 MB cap; path-traversal rejection (tested) | `clinic_app/config.py`, `app.py` |

## Hardening applied in this change (safe, behavior-preserving)

1. **CSRF exemption mechanism was dead code — now functional.** Several server-to-server / public endpoints declared `is_csrf_exempt = True` (`billing.morning_webhook`, `calendar.api_public_calendar_book`, `calendar.api_open_slot_book`, `messaging.contact_inquiry`), but **nothing consumed that flag**, so `CSRFProtect` would reject the external POSTs (e.g. the Morning payment webhook) in production. Added a consumer right after `CSRFProtect(app)` that calls `csrf.exempt()` for every view flagged `is_csrf_exempt`, and flagged the Google Drive webhook `google_docs.gdoc_webhook` (it is authenticated by `_validate_gdoc_webhook_request()` and cannot carry a CSRF token). Verified: a normal POST without a token still returns `400`, while the webhook reaches its own auth check (`403`).
2. **HSTS header** added to `apply_security_headers`, emitted **only** over HTTPS (direct `request.is_secure` or `X-Forwarded-Proto: https` from the TLS-terminating proxy) so a plain-HTTP dev origin is never told to force TLS. Value: `max-age=31536000; includeSubDomains`.
3. **Rate-limited the public `/contact-inquiry` form** (unauthenticated + CSRF-exempt) at 5 requests / 5 minutes per client IP, reusing the existing `_check_db_rate_limit` helper — mirrors the authenticated `contact_admin` limiter and closes a spam/abuse gap.

## Recommendations NOT auto-applied (deployment/behavior-sensitive — decide per environment)

These are real improvements but change deployment behavior or require product decisions, so they are documented rather than silently changed:

1. **`SESSION_COOKIE_SECURE` defaults to off.** It should be `1`/`true` in every TLS deployment so session cookies are never sent over plain HTTP. Set `SESSION_COOKIE_SECURE=1` in production env (`app.py` reads it). Left as-is to avoid breaking local HTTP dev.
2. **Morning payment webhook has no signature verification.** `/webhooks/morning` is (correctly) CSRF-exempt but accepts any POST — anyone who learns the URL could post payment status. Add HMAC signature verification using a shared secret from the Morning dashboard before trusting payloads.
3. **Secrets stored in plaintext at rest.** Google OAuth tokens (`google_calendar_tokens.token_json`) and Morning API credentials (`site_settings`) are stored unencrypted in SQLite. Consider encrypting them with the existing Fernet key material (`clinic_app/backup.py` pattern) so a DB leak does not expose live tokens.
4. **CSP allows `'unsafe-inline'` and `'unsafe-eval'`.** This significantly weakens XSS mitigation. Migrating to nonce/hash-based inline scripts and removing `'unsafe-eval'` is a larger templating effort but meaningfully hardens the app.
5. **`X-Forwarded-For` is trusted first-hop for rate-limit buckets** without a trusted-proxy allowlist, so a spoofed header could rotate buckets. Constrain to the known proxy (e.g. `ProxyFix` with an explicit hop count) in production.
6. **Default admin username** falls back to `lioraloni` when `ADMIN_USERNAME` is unset. Always set `ADMIN_USERNAME`/`ADMIN_PASSWORD` explicitly on first deploy.

## Notes

- No SQL injection surface was found in application routes: queries are parameterized, and the few dynamic-identifier statements (migrations, admin export, backup restore) use hardcoded/table-metadata names, not HTTP input. No `eval`/`render_template_string` in application code.
- `subprocess` is used only by the optional Bandit/pip-audit security-scan feature.
