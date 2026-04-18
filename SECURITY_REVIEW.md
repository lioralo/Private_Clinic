# Security Review (2026-04-18)

## Scope
- Application-level static review of authentication/session/configuration/upload/public endpoints.
- Validation of existing automated security tests.

## Validation Performed
- Ran `python -m unittest -v tests.test_security` (all tests passed).
- Ran full recommended regression suite to ensure security-adjacent changes did not break behavior.

## Findings

### High
1. Default Flask secret fallback is weak in production misconfiguration.
- Location: `app.py` (`app.secret_key = os.environ.get('SECRET_KEY', 'dev')`)
- Risk: If `SECRET_KEY` is missing in production, session integrity can be compromised.
- Recommended fix: Fail fast in non-testing when `SECRET_KEY` is missing/weak; keep insecure fallback only for explicit local dev mode.

2. Hard-coded admin bootstrap credentials exist in code path.
- Location: `_seed_admin_user` in `app.py`.
- Risk: Predictable credentials are a critical account takeover risk if bootstrap flow runs unexpectedly.
- Recommended fix: Require `DEFAULT_ADMIN_PASSWORD` env var (or generated one-time password printed only on first boot), set `force_password_change=1`, and remove embedded default password.

### Medium
1. Google Docs webhook trust model is minimal.
- Location: `/api/gdoc/webhook`.
- Risk: Endpoint trusts `X-Goog-Channel-ID` only; spoofing may trigger unwanted sync work.
- Recommended fix: Validate Google notification headers (resource state/id), store/verify channel metadata, and add request authenticity checks where possible.

2. Public booking endpoints are CSRF-exempt and open by design.
- Location: `/api/calendar/public/<token>/book`, `/api/calendar/open/<token>/book`.
- Risk: Token brute force / abuse attempts if token entropy/monitoring/rate limits are insufficient.
- Recommended fix: Add endpoint-level throttling/rate limiting, abuse logging, and optional CAPTCHA for repeated attempts.

### Low
1. Missing explicit secure cookie and hardening headers defaults.
- Location: Flask app configuration/global response handling.
- Risk: Reduced defense in depth.
- Recommended fix: Set cookie security flags and add baseline headers:
  - `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE`
  - `X-Content-Type-Options`, `X-Frame-Options`, strict `Referrer-Policy`, and CSP tuned to frontend requirements.

## Priority Implementation Plan
1. Remove hard-coded admin credentials and enforce secure bootstrap flow.
2. Enforce strong `SECRET_KEY` policy in non-dev runtime.
3. Add rate limiting for public booking endpoints.
4. Add hardened security headers and cookie flags.
5. Strengthen webhook verification logic.

## Suggested Next Security Tests
- Add tests for missing/weak `SECRET_KEY` startup behavior in production mode.
- Add tests ensuring no default admin password path is reachable without explicit env configuration.
- Add abuse/rate-limit tests for public booking endpoints.
- Add tests for security headers on authenticated and public routes.
