# Changes Documentation

---

## Session 81

**Date:** 2026-06-29

**Objective:** Fix Google OAuth credentials for production, fix admin password persistence, fix TOTP setup flow, update UI for password change without 2FA, expire stale pending secrets.

**Release Summary:**

1. **Google OAuth production fix**
   - Updated `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in production `.env` to match Google Cloud Console credentials.
   - Added redirect URI `https://clinic.lior-clinic.org/admin/google-calendar/callback`.
   - Removed `[GCAL DEBUG]` print statements from callback endpoint.

2. **Admin password persistence**
   - Set `ADMIN_PASSWORD_RESET=0` in production `.env` so password hash is no longer overwritten on container restart.
   - Recreated container with `--force-recreate` to pick up the new env value.
   - Cleared stale `rate_limits` entries that were blocking login (680s lockout).

3. **TOTP authenticator fixes**
   - Added `import time` to fix `NameError: name 'time' is not defined` in `setup_authenticator()`.
   - Added `pending_totp_created_at` timestamp to session; stale pending secrets (>10 min) auto-expire on profile page load.
   - This prevents showing a stale QR code / verify form from an old browser session.

4. **Password change without TOTP**
   - Made `otp_code` field optional in the "Change Admin Password" form when TOTP is not enabled.
   - Backend already accepted password change without `otp_code`; only the HTML `required` attribute blocked it.
    - Updated help text to clarify that authenticator code is only needed if 2FA is enabled.

5. **TOTP UI text update**
    - Renamed "Start Authenticator Setup" to "Set Up Authenticator" for clarity.
    - Added "not configured" info message when TOTP is disabled.

---

## Session 82

**Date:** 2026-07-05

**Objective:** Implement structured treatment plans with SMART goals, clinical outcome measures (PHQ-9/GAD-7), SMS appointment reminders, PWA mobile support, and unify calendar schema.

**Release Summary:**

1. **Structured Treatment Plans** (`/treatment-plans/`)
    - New blueprint `treatment_plans.py` with full CRUD for plans + goals.
    - SMART goals with progress percentage, status per goal (active/in_progress/achieved/discontinued/revised).
    - Template: `treatment_plan_view.html` with per-goal progress bars + `treatment_plan_form.html` with dynamic JS add/remove goals.
    - Tables: `treatment_plans` + `treatment_plan_goals` (Alembic `e7a2b9c4d1f0`).

2. **Clinical Outcome Assessments** (`/assessments/`)
    - New blueprint `assessments.py` with take-assessment flow + results view.
    - PHQ-9 (depression, 9 items, 0-27) and GAD-7 (anxiety, 7 items, 0-21) pre-seeded in `assessment_types`.
    - Scoring engine in `utils.py` (`_score_assessment()`) with sum/average methods + severity level lookup.
    - Templates: `assessment_take.html` (dynamic question renderer), `assessment_results.html` (grouped by type + Chart.js line chart over time).
    - Tables: `assessment_types` + `assessments` (stores raw scores JSON, total, severity, interpretation).

3. **SMS Appointment Reminders**
    - `send_sms()` utility in `app.py` — sends via Twilio when `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/`TWILIO_FROM_NUMBER` are configured; logs to `sms_logs` otherwise.
    - `_send_appointment_sms_reminders()` runs alongside email reminders in the APScheduler job (every 5 min, 7-day lookahead, 2-hour send window).
    - Per-patient toggle: `reminder_sms_enabled` checkbox in `edit_patient.html`.
    - Table: `sms_logs` for audit trail of all SMS attempts.

4. **PWA (Progressive Web App)**
    - `static/manifest.json` — standalone display, theme color `#0d6efd`, app icons.
    - `static/service-worker.js` — cache-first for static assets, network-first for API calls.
    - `templates/layout.html` — manifest link, meta tags (theme-color, apple-mobile-web-app-capable), service worker registration, install button in sidebar.
    - Install prompt intercepted via `beforeinstallprompt` event.

5. **Calendar Schema Refactor**
    - Unified `availability` table replacing `slots_override` + `vacancy_recurring`.
    - Recurrence logic extracted to `recurring_occurrences_between()` and `get_cancelled_dates()` in `utils.py`. Recurrence days parsed by `parse_recurrence_days()`. Cancelled dates stored as JSON array (`cancelled_dates`).
    - Hebrew translations updated (~90 new keys).

6. **Infrastructure**
    - Both new blueprints registered in `app.py` with legacy URL aliases for backward compat.
    - `from_json` Jinja2 filter registered.
    - Patient detail page tabs updated with Treatment Plans + Assessments links.
    - Migration `e7a2b9c4d1f0` applied (depends on `c9199256007c`).
    - `twilio` package not in `requirements.txt` — install separately if SMS sending is needed.

**Files Modified:**
- `app.py`, `clinic_app/utils.py`, `clinic_app/routes/calendar.py`
- `templates/layout.html`, `templates/edit_patient.html`, `templates/patient_detail.html`
- `translations/he.json`
- `tests/test_app.py`, `tests/test_fix_calendar_times.py`, `tests/test_security.py`
- `alembic/versions/e7a2b9c4d1f0_add_treatment_plans_and_assessments.py`
- `.gitignore`

**Files Added:**
- `clinic_app/routes/treatment_plans.py`, `clinic_app/routes/assessments.py`
- `templates/treatment_plan_view.html`, `templates/treatment_plan_form.html`
- `templates/assessment_take.html`, `templates/assessment_results.html`
- `static/manifest.json`, `static/service-worker.js`

**Test Results:** 339 total tests, all passing. Test run ~8 min (known performance issue).

---

## Session 80

**Date:** 2026-06-29

**Objective:** Security hardening, patient TOTP support, fixes for auth/admin redirects, and production deployment prep.

**Release Summary:**

1. **Security scanning dashboard** (`/admin/security/log`)
   - CSP headers injection (`form-action 'self'`, script/style nonces).
   - Programmatic Bandit & `pip-audit` scanners with cron scheduling.
   - Security health badges, settings forms, and accordion scan reports.

2. **Cryptographic key separation**
   - Backup keys moved from `secure_backups/` to `.clinic_keys/` with `700` permissions.
   - `_ensure_backup_key_consistency()` in `app.py` fixed to use `KEY_DIR`.

3. **MFA recovery codes**
   - 5 recovery codes generated on authenticator enrollment (admin + patient).
   - Login fallback: recovery codes consumed one-time.
   - Recovery codes displayed with "Print Codes" button.

4. **Patient TOTP setup**
   - New `/patient/settings` route with QR code + recovery codes display.
   - New `templates/patient_settings.html`.
   - "Settings" link in patient nav bar.

5. **Rate limiting (DB-backed)**
   - Patient cancellations: 5/hour.
   - Patient booking requests: 5/hour.
   - Contact admin messages: 10/minute.
   - Registration: 3/15min. Password reset: 5/15min. Login: 10/15min + lockout.

6. **Bug fixes**
   - `auth.py`: MFA flash message now role-aware ("admin" vs "patient" account).
   - `admin.py`: `setup_authenticator` redirects patients to `patient_settings` instead of `admin_profile`.
   - `admin.py`: Restored `admin_change_password` / `admin_restore_backup` / `admin_profile_name` redirect targets after refactor.
   - Lockout email body: plain-text alert stripped emoji.
   - Security scanner: `shutil.which()` check for bandit/pip-audit availability.

7. **Production prep**
   - `bandit` and `pip-audit` installed in production venv.
   - `.clinic_keys/` permissions locked down (`700`), stale key removed from `secure_backups/`.

**Verification:**
- `pytest tests/test_security.py tests/test_backup_db.py -q` — **43/43 passed**.
- `git push origin main` — commit `8727531`.

## Session 79

**Date:** 2026-05-27

**Objective:** Make group Google Docs parsing closer to the real clinic format, improve imported private-note wording, and add a fuller verification sample.

**Release Summary:**

1. **Closer-to-real group-doc parsing**
  - Extended the Google Docs group parser to accept semicolon-separated one-line participant and missing-entry lists with inline notes, in addition to the previous per-line format.
  - Kept the existing parser behavior for plain comma-separated name lists and the older structured Hebrew templates.

2. **Cleaner imported patient notes**
  - Reworked imported private notes from group sessions into a clearer Hebrew block that includes group name, meeting title, date/time, status, and the participant note or absence reason.

3. **Expanded verification sample**
  - Added a multi-session dummy group-doc sample covering per-line notes, semicolon-separated inline entries, and plain participant lists so the import behavior can be reviewed in the site.

4. **Verification**
  - Passed: `python -m unittest tests.test_google_docs_integration` (`21` tests)
  - Confirmed local import into the verification group created three completed group sessions with attendance rows and patient private notes.

## Session 78

**Date:** 2026-05-27

**Objective:** Improve CRM appointment visibility and make group Google Docs sync populate patient notes more completely.

**Release Summary:**

1. **CRM next-appointment display fix**
  - Added a fallback for recurring patients so the CRM table now fills `next_appointment_date` and `next_appointment_time` when the base appointment row is past-dated or incomplete.

2. **Group Docs attendance parsing**
  - Kept the Google Docs parser backward-compatible for existing tests while also preserving inline notes from `משתתפים` and `חסרים` as structured metadata.
  - Group sync now uses that metadata to mark attendees present, record missed reasons, and carry the session note text into the patient-side note.

3. **Patient private note migration**
  - Group sync now writes/updates patient private notes with the group session id, group name, session date, and session time so the patient page shows the related context alongside the imported note.

4. **Verification**
  - Passed: `python -m unittest tests.test_google_docs_integration` (`19` tests)
  - Passed: `python -m unittest tests.test_app.ClinicTestCase.test_group_recurrence_update_future_and_attendance_missed_reason tests.test_app.ClinicTestCase.test_individual_treatment_note_can_record_missed_reason`
  - Passed: `python -m unittest tests.test_app.ClinicTestCase.test_group_recurrence_update_future_and_attendance_missed_reason tests.test_app.ClinicTestCase.test_individual_treatment_note_can_record_missed_reason tests.test_google_docs_integration` (`21` tests)

## Session 77

**Date:** 2026-05-08

**Objective:** Harden Google OAuth callback handling and expand verification around real production return paths.

**Release Summary:**

1. **Server-Side Pending OAuth Recovery (Reliability)**
  - Google OAuth connect now stores the pending handshake server-side, including the initiating admin, redirect URI, and PKCE verifier.
  - The callback can now complete successfully even when the browser loses the clinic session cookie during the return from Google.

2. **Anonymous Signed-State Guard (Security)**
  - A valid signed OAuth state alone no longer authorizes an anonymous callback.
  - The callback now requires either the current authenticated admin session or a matching stored pending OAuth record for an active admin.

3. **Expanded Google OAuth Regression Coverage (Tests)**
  - Added tests for:
    - defaulting to all integrations when none are selected,
    - recovering the callback after session loss,
    - declined consent from Google,
    - missing-code cancellation returns,
    - rejecting anonymous callbacks that only present a signed state.

4. **Verification**
  - Passed: `SECRET_KEY=test-secret FLASK_DEBUG=1 /usr/bin/python3 -m unittest tests.test_google_oauth -v` (`28` tests)
  - Passed: `SECRET_KEY=test-secret FLASK_DEBUG=1 /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'` (`361` tests)
  - Passed: `SECRET_KEY=test-secret FLASK_DEBUG=1 /usr/bin/python3 -m unittest -v test_export_data test_import_clinic_data test_google_calendar` (`13` tests)

---

## Session 76

**Date:** 2026-05-07

**Objective:** Resolve persistent production issues where Google Connect/Disconnect controls were not visible and Docs Sync did not run reliably.

**Release Summary:**

1. **Server-rendered Google Integration State (Reliability)**
  - `admin_profile` now computes Google integration status server-side and injects it into the template.
  - The profile page now renders Connect/Disconnect controls correctly even if client-side status fetch fails.

2. **Always-Visible Integration Panel (UX)**
  - Google integration accordion now opens by default to keep controls immediately visible.
  - Initial status badge, active integrations, and calendar selector are rendered from server state.

3. **Manual Docs Sync Fallback (Behavior)**
  - Manual `Sync Now` now falls back to syncing all connected docs when no specific sync targets were selected.
  - Prevents the common “nothing runs” case when docs are connected but selection list is empty.

4. **Dynamic Refresh Fallback (Frontend)**
  - If async status refresh fails, UI preserves server-rendered state instead of replacing it with an empty/error-only placeholder.

5. **Verification**
  - Added regression tests for server-rendered Connect/Disconnect visibility.
  - Added regression test for manual sync fallback with empty target selection.
  - Test results: `341/341` passing in `tests/`.

---

## Session 75

**Date:** 2026-05-07

**Objective:** Fix Google integration connect/disconnect state visibility so admin actions always match active connection status.

**Release Summary:**

1. **Google Connect/Disconnect State Rendering (UI)**
  - Updated admin profile integration script to render a complete state on every status response.
  - UI now explicitly toggles both directions:
    - connected: show **Disconnect Google**, hide connect form
    - disconnected: show connect form, hide disconnect action
  - Clears and rebuilds active integrations and calendar selector each refresh to avoid stale UI.

2. **Status Fetch Freshness (UI Reliability)**
  - Added cache-busting query parameter to the Google status request to avoid stale cached responses after OAuth redirects.

3. **Verification**
  - Google OAuth tests still pass, including disconnect behavior and enabled integrations coverage.
  - Full test suite remains green.

---

## Session 74

**Date:** 2026-05-05

**Objective:** Fix deployment helpers so AWS receives the intended latest branch and the current local checkout.

**Release Summary:**

1. **Branch-Pinned Remote Update (Deployment)**
  - `scripts/migrate_to_aws.sh` now accepts `--git-branch`.
  - Remote deployment no longer updates whichever branch happens to be checked out on the server.
  - The script now explicitly clones, fetches, checks out, and fast-forwards the requested branch before deploying.

2. **Current Local Checkout Deployment (Deployment)**
  - `deploy_now.sh` now detects the active local branch and prints the exact local commit being deployed.
  - After the migration step, it runs `scripts/deploy_local_bundle_to_aws.sh` so the live server receives the current local checkout rather than relying only on the server-side repo state.

3. **Backup Path Fix (Deployment)**
  - `deploy_now.sh` now calls `python3 scripts/backup_db.py`, matching the actual repository layout.

4. **Verification**
  - Shell syntax validation passed for the updated deployment scripts.
  - Dry-run output confirmed that the AWS migration flow now targets the requested branch explicitly and prints the deployed commit.

---

## Session 73

**Date:** 2026-05-05

**Objective:** Resolve live visibility issues for portal access controls and stabilize about-page messaging/map behavior.

**Release Summary:**

1. **Portal Access Visibility Fix (UI)**
  - Kept the Portal Access section as an always-visible standalone card in the patient detail sidebar (not hidden in the collapsed Actions accordion).
  - Verified visually that "Grant Portal Access" appears for patients with no account and that status/action buttons appear after granting access.

2. **About Page Messaging CTA Reliability (UI)**
  - Message action is now role-aware and always visible on the About page:
    - patient: opens messages offcanvas,
    - admin: links to CRM/Message Center,
    - logged-out visitor: links to login.

3. **Google Maps Link Normalization (Logic + UI)**
  - Added server-side normalization for About map URLs via `_build_about_map_urls`.
  - Supports regular Google Maps links and converts common URL patterns (`q`, `query`, `destination`, `/maps/place/...`) into embeddable URLs.
  - Falls back to "Open in Google Maps" when embedding cannot be derived.

4. **Admin Settings Guidance (UX)**
  - Added helper text in About settings indicating regular Google Maps links are accepted and auto-embedded when possible.

5. **Verification**
  - Visual verification completed locally:
    - About page shows working WhatsApp, mailto, messaging CTA, and embedded map.
    - Patient detail shows working grant access flow and post-grant portal status/actions.
  - Tests: `192/192` in `tests/` and `13/13` root-level tests passed.

---

## Session 72

**Date:** 2026-05-04

**Objective:** About-page contact improvements and patient portal access management by admin.

**Release Summary:**

1. **About Page — Clickable Phone & Email (Improved)**
   - Phone number is now a WhatsApp link (`wa.me/...`) with a secondary `tel:` "Call" link and WhatsApp icon.
   - Email address is now a `mailto:` link.

2. **About Page — Google Maps Embed Fix (Improved)**
   - The map section now auto-detects whether the stored URL is a proper embed URL (containing `maps/embed`).
   - If it is, the `<iframe>` is rendered as before.
   - If not, a "Open in Google Maps" button is shown instead — avoiding the `X-Frame-Options` / "refused to connect" error that occurs with standard map share links.

3. **About Page — Messaging Button for Patients (New)**
   - Logged-in patients now see a "Message the clinic" button that opens the existing in-app messaging offcanvas panel directly from the about page.

4. **Patient Portal Access Management — Admin UI (Improved)**
   - The Portal Access card on `patient_detail` now shows: account username, active/disabled badge, "Must change password" warning badge.
   - Three action buttons: **Disable/Enable Access** (existing toggle), **Change Credentials** (collapsible inline form), **Reset Password** (new).
   - Patients without a portal account see an inline "Grant Portal Access" form.

5. **Grant Portal Access — Force Password Change on First Login (New)**
   - When admin grants or updates patient portal credentials via `manage_access`, `force_password_change = 1` is set.
   - An email notification is sent to the patient's email address with their username and temporary password, informing them they must change it on first login.

6. **Reset Portal Password Route (New)**
   - New `POST /patient/<id>/reset_portal_password` route.
   - Generates a cryptographically random temporary password (`secrets.token_urlsafe(12)`), stores it hashed, sets `force_password_change = 1`.
   - Sends an email to the patient with their username and new temporary password.

7. **Patient Force-Password-Change Enforcement (New)**
   - `_login_redirect_for_user` now checks `force_password_change` for patient-role users.
   - Patients with the flag set are redirected to `/patient/change-password` instead of their home page.
   - New `GET/POST /patient/change-password` route validates password strength (via existing `_validate_password_strength`), clears the flag, and bumps `session_version` to invalidate any concurrent sessions.

8. **Patient Change Password Template (New)**
   - New `templates/patient_change_password.html`: clean card-based form prompting for new password and confirmation.

9. **Route Baseline Updated**
   - Increased from 152 to 157 routes (added `patient_change_password`, `reset_portal_password`).

10. **Tests**
    - All 205 tests pass (192 in `tests/` + 13 root-level).

---

## Session 70 (WIP - not merged)

**Date:** 2026-05-04

**Objective:** Continue security hardening and UX improvements — security metrics dashboard widget, audit log viewer, rate-limited registration, patient field validation, and appointment duration bounds.

**Release Summary:**

1. **Security Metrics Dashboard Widget (New)**
- Added `_get_dashboard_security_metrics(db)` helper that queries the last 24 h of `auth_*` audit events.
- Admin dashboard now shows a security strip with: failed logins, failed 2FA attempts, password-reset requests, and disabled-account login attempts.
- Widget highlights counts in red when thresholds are exceeded.
- Expandable list of recent failures for quick triage.
- "Full log" button links to new `/admin/security-log` viewer.

2. **Admin Security Audit Log Viewer (New)**
- New route `/admin/security-log` (GET) with paginated, filterable view of all `auth_*` audit events.
- Filters: event type dropdown + keyword search on action/details.
- Color-coded event badges (red = failures, green = success, yellow = resets).
- Added to admin sidebar as "Security Log" nav entry.
- Route baseline updated to 151 routes.

3. **Registration Rate Limiting (New)**
- Added per-IP sliding-window rate limit on the public `/register` endpoint.
- Configurable via: `REGISTER_RATE_LIMIT_MAX` (default 5) and `REGISTER_RATE_LIMIT_WINDOW_SECONDS` (default 3600).
- Returns HTTP 429 with friendly flash message when exceeded.

4. **Patient Field Input Validation (New)**
- Added `_validate_patient_fields(name, phone, birth_date, email)` helper.
- Validates: phone number format (7–15 digits, `+` prefix allowed), email format, birth date as YYYY-MM-DD.
- Applied at: `add_patient` POST and `edit_patient` POST.

5. **Appointment Duration Bounds Validation (New)**
- Added `_validate_appointment_duration(duration_minutes)` helper.
- Enforces: minimum 5 minutes, maximum 480 minutes (8 h).
- Applied at the main `/api/calendar/book` endpoint.

6. **Tests Updated**
- New tests: `test_admin_security_log_accessible_by_admin`, `test_admin_security_log_redirects_non_admin`, `test_registration_rate_limit_blocks_excess_registrations`, `test_validate_patient_fields_rejects_bad_phone`, `test_validate_patient_fields_rejects_bad_email`, `test_validate_patient_fields_rejects_bad_birth_date`, `test_validate_patient_fields_accepts_valid_data`.

---

## Session 69 (WIP - not merged)

**Date:** 2026-05-04

**Objective:** Continue security/ops improvements with admin SMTP diagnostics, stronger password policy enforcement, and automated retention cleanup.

**Release Summary:**

1. **Admin SMTP Diagnostics (New)**
- Added admin endpoints:
  - `/admin/smtp/health` (connectivity/configuration status)
  - `/admin/smtp/test` (send a test message to an admin-selected address)
- Added SMTP diagnostics panel to Admin Profile UI with status badges and test-send action.

2. **Stronger Password Policy (Expanded)**
- Added centralized password policy validation (minimum length + composition checks + username/email overlap guard).
- Applied policy to:
  - password reset completion
  - admin password change flow
- Added inline password-strength hint feedback in admin profile form.

3. **Retention and Cleanup Guard (New)**
- Added periodic retention cleanup guard for security-related records.
- Configurable retention controls:
  - `SECURITY_RETENTION_CHECK_INTERVAL_SECONDS`
  - `AUDIT_LOG_RETENTION_DAYS`
  - `PASSWORD_RESET_TOKEN_RETENTION_DAYS`
- Cleanup covers stale audit rows and old reset tokens.

4. **Admin Security Visibility (New)**
- Admin profile now shows recent `auth_*` audit events for quick security triage.

5. **Contract/Test Updates (WIP)**
- Added/updated tests for:
  - SMTP health endpoint behavior
  - weak password rejection in reset/change flows
- Updated route baseline for new SMTP endpoints.

6. **Debug / Verification Notes**
- Static diagnostics are clean on modified files.
- Runtime unit execution in this environment is still blocked by missing `pyotp` dependency.

---

## Session 68

**Date:** 2026-05-04

**Objective:** Continue security roadmap with delivery-ready password reset handling and session revocation hardening.

**Release Summary:**

1. **SMTP-Based Password Reset Delivery**
- Added SMTP configuration support (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS`).
- Password reset links are no longer written to logs in normal runtime.
- In `TESTING` mode only, reset link remains flashed to support deterministic tests.

2. **Reset Token Lifecycle Cleanup**
- Added periodic cleanup for used/expired password reset tokens.
- Cleanup runs opportunistically during reset request/reset flows with a guard cadence.

3. **Session Revocation Model**
- Added `users.session_version` to schema and runtime migration path.
- Session now stores version at login and validates it on each authenticated request.
- Password changes/resets increment `session_version`, forcing all older sessions to re-authenticate.

4. **Additional Security Tests**
- Added tests ensuring:
  - reset link is not exposed when not in testing mode,
  - active session is invalidated when `session_version` changes.

5. **Baseline Contract Update**
- Updated route baseline to include password reset endpoints.

---

## Session 67

**Date:** 2026-05-04

**Objective:** Implement the next security and robustness tranche: password reset flow, auth audit coverage, and safe error handling.

**Release Summary:**

1. **Password Reset Flow (New)**
- Added `/forgot-password` and `/reset-password/<token>` routes.
- Added secure reset token storage in DB (`password_reset_tokens`) with:
  - token hash (SHA-256, no plaintext storage)
  - expiry timestamp
  - single-use marker (`used_at`)
  - requester IP tracking
- Added request throttling for password reset attempts with configurable limits.
- Added login-page entry point (`Forgot password?`) and dedicated reset templates.

2. **Authentication Audit Events (Expanded)**
- Added auth-related audit entries for:
  - login password success/failure
  - 2FA success/failure
  - logout
  - password reset requested/completed/invalid
  - authenticator setup start/enable/disable
  - admin password change

3. **Production-Safe Error Handling (New)**
- Added global 404 and 500 handlers.
- JSON responses are returned for API-style requests.
- User-friendly HTML error pages added for browser requests (`404.html`, `500.html`).

4. **Schema & Migration Updates**
- Added `password_reset_tokens` table to `schema.sql` for fresh installs.
- Added same table and indexes in runtime migration routine for existing deployments.

5. **Regression Coverage Added**
- Extended `tests/test_security.py` with tests for:
  - reset request token generation
  - reset token password update flow
  - invalid token rejection
  - reset request throttling

6. **Debug / Verification Notes**
- Static editor diagnostics for modified files showed no syntax/lint issues.
- Runtime tests still require project dependencies installed in the execution environment.

---

## Session 66

**Date:** 2026-05-04

**Objective:** Start roadmap implementation with authentication hardening: add login brute-force protection while preserving current inactivity timeout behavior.

**Release Summary:**

1. **Login Rate-Limit / Lockout (New)**
- Added login brute-force protections in `clinic_app/routes/auth.py`.
- Protection key combines client IP and normalized username.
- Added configurable controls:
  - `LOGIN_RATE_LIMIT_MAX_ATTEMPTS` (default `5`)
  - `LOGIN_RATE_LIMIT_WINDOW_SECONDS` (default `300`)
  - `LOGIN_RATE_LIMIT_LOCKOUT_SECONDS` (default `900`)
- Behavior:
  - Blocks new login attempts while lockout is active.
  - Clears failure bucket on successful credential validation.

2. **Configuration Surface Added**
- Added the three login rate-limit config values in `app.py` from environment variables so production tuning does not require code edits.

3. **Regression Coverage Added**
- Added tests in `tests/test_security.py`:
  - `test_login_rate_limit_blocks_after_repeated_failures`
  - `test_login_rate_limit_resets_after_successful_login`

4. **Debug / Verification**
- Confirmed inactivity timeout was already implemented and covered by existing tests.
- Attempted local test execution with:
  - `python3 -m unittest tests/test_security.py`
- Local environment blocker observed:
  - `ModuleNotFoundError: No module named 'pyotp'`
  - `python3 -m pip` unavailable on this host (`No module named pip`)
- Static diagnostics for modified files reported no editor/lint errors.

---

## Session 65

**Date:** 2026-05-04

**Objective:** Reduce appointment-management friction by letting admins update appointment status directly from the patient detail page.

**Release Summary:**

1. **Inline Appointment Status Update API**
- Added route: `/api/appointment/<appointment_id>/status` (POST, admin-only).
- Accepts `completed`, `no_show`, `scheduled`, and `cancelled`.
- Reuses the existing appointment status validation and audit-log behavior.

2. **Patient Detail Appointment Controls**
- Updated the appointment list in `patient_detail.html` to show status badges inline.
- Added one-click actions for `Mark Complete`, `Mark No Show`, and `Mark Cancelled`.
- Added confirmation before mutation and success/error toast feedback through the existing toast helper.

3. **Localization**
- Added appointment-related translation keys for the new inline controls and badge labels.

4. **Regression Coverage Added**
- New tests in `tests/test_app.py`:
  - `test_api_appointment_status_update_inline`
  - `test_patient_detail_appointment_shows_status_badge`
- Confirms DB update, audit log insert, and patient-detail rendering of the new controls.

5. **Validation**
- Focused tests:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest -v tests.test_app.ClinicTestCase.test_api_appointment_status_update_inline tests.test_app.ClinicTestCase.test_patient_detail_appointment_shows_status_badge tests.test_app.ClinicTestCase.test_patient_detail_sections_render`
- Full suite:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'`
- Root-level suites:
  - `/usr/bin/python3 -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 64

**Date:** 2026-05-04

**Objective:** Improve admin dashboard focus on load by keeping only Today’s Agenda expanded and collapsing all other dashboard cards by default.

**Release Summary:**

1. **Dashboard Load Behavior (Improved)**
- Updated `admin_home.html` dashboard scripts so all `details.dashboard-fold` sections are collapsed on initial load, except `today-schedule`.
- This keeps the first screen focused and reduces visual noise when opening the dashboard.

2. **Safer Quick Action Handler**
- Wrapped the `bulkCompletePastBtn` click binding with a null-check guard to avoid runtime JS errors if the button is absent in future template variations.

3. **Regression Coverage Added**
- New test: `test_admin_dashboard_defaults_to_today_section_open` in `tests/test_app.py`.
- Verifies `/admin/dashboard` renders `today-schedule` as open and key other sections as closed by default.

4. **Validation**
- Focused tests:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest -v tests.test_app.ClinicTestCase.test_admin_dashboard_defaults_to_today_section_open tests.test_app.ClinicTestCase.test_bulk_complete_past_appointments tests.test_app.ClinicTestCase.test_admin_can_export_appointments_csv`
- Full suite:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'`
- Root-level suites:
  - `/usr/bin/python3 -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 63

**Date:** 2026-05-03

**Objective:** Add a bulk "mark past appointments as completed" admin action to improve data hygiene and reduce manual status cleanup.

**Release Summary:**

1. **New Bulk Complete Endpoint**
- Added route: `/api/admin/bulk_complete_past_appointments` (POST, admin-only).
- Updates all `scheduled` appointments where `appointment_date < DATE('now')` to `status = 'completed'`.
- Returns JSON `{updated: N}` with the count of rows changed.
- Writes an audit log entry for the bulk operation.

2. **Dashboard Quick Action Button**
- Added `Mark Past Appointments as Completed` button in the Quick Actions panel of `admin_home.html`.
- Confirms before executing via `confirm()` dialog.
- Shows a toast (or alert fallback) with the number of appointments updated.

3. **Localization**
- Added translation keys: `Mark Past Appointments as Completed`, `past appointments marked as completed.`, `Mark all past scheduled appointments as completed?`.

4. **Regression Coverage Added**
- New test: `test_bulk_complete_past_appointments` in `tests/test_app.py`.
- Inserts a past scheduled appointment, calls the endpoint, verifies `updated >= 1` and that no past scheduled appointments remain.

5. **Validation**
- Focused tests: `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest -v tests.test_app.ClinicTestCase.test_bulk_complete_past_appointments`
- Full suite: `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'`
- Root-level suites: `/usr/bin/python3 -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 62

**Date:** 2026-05-03

**Objective:** Continue the roadmap with an operational quick win: appointment CSV export for admins.

**Release Summary:**

1. **New Admin CSV Export Endpoint**
- Added route: `/api/admin/export_appointments.csv`.
- Admin-only access.
- Exports appointment rows joined with patient fields in UTF-8 CSV format (Excel-friendly BOM).
- Supports optional query filters:
  - `from_date`
  - `to_date`
  - `status` (`scheduled`, `completed`, `cancelled`)

2. **Dashboard Quick Action**
- Added an `Export Appointments CSV` quick-action button to `admin_home.html`.
- One-click export from admin dashboard without leaving workflow.

3. **Localization**
- Added translation key: `Export Appointments CSV`.

4. **Regression Coverage Added**
- New test in `tests/test_app.py`: `test_admin_can_export_appointments_csv`.
- Verifies successful admin export response, CSV headers, and expected row content.

5. **Validation**
- Focused tests:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest -v tests.test_app.ClinicTestCase.test_admin_can_export_appointments_csv tests.test_app.ClinicTestCase.test_add_patient tests.test_app.ClinicTestCase.test_patient_detail_sections_render`
- Full suite:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'`
- Root-level suites:
  - `/usr/bin/python3 -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

**Date:** 2026-05-03

**Objective:** Continue roadmap implementation by adding overdue follow-up visibility in the patient detail workflow, then validate and merge.

**Release Summary:**

1. **Patient Detail Follow-Up Indicator (New)**
- Added backend helper `_get_patient_followup_status(...)` to compute follow-up risk from note recency and upcoming schedule.
- A patient is flagged when the latest note is older than 30 days and no upcoming appointment is booked.
- Added severity grading (`warning` at 30+ days, `danger` at 60+ days) for clearer triage.

2. **Patient Detail UX Update**
- Added a follow-up warning card in the right-side actions panel of `patient_detail.html`.
- Card includes:
  - no-upcoming-appointment reminder,
  - last note date,
  - days since last note.

3. **Localization**
- Added Hebrew translations for new labels:
  - `Follow-up needed`
  - `Last note date:`
  - `Days since last note:`

4. **Debug / Verification**
- Focused tests:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest -v tests.test_app.ClinicTestCase.test_add_patient tests.test_app.ClinicTestCase.test_patient_detail_sections_render tests.test_app.ClinicTestCase.test_crm_patient_view_shows_all_and_candidates_buttons`
- Full suite:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'`
- Root-level suites:
  - `/usr/bin/python3 -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

**Date:** 2026-05-03

**Objective:** Continue the implementation roadmap by improving form maintainability and consistent user feedback UX.

**Release Summary:**

1. **Unified Flash + Toast Feedback UX**
- Added category-aware flash rendering in shared layout to support `success`, `error/danger`, and default info styles.
- Removed duplicated flash markup blocks in admin/patient/public layout branches by centralizing rendering through one macro.
- Added global `window.showAppToast(...)` helper for consistent non-blocking notifications.
- Replaced blocking alert behavior in notification mark-read flow and intake async actions with toast feedback.

2. **Shared Patient Form Components**
- Added reusable Jinja macro file: `templates/patient_form_macros.html`.
- Refactored `templates/add_patient.html` and `templates/edit_patient.html` to use shared macros for identity/contact/core patient fields.
- Preserved field names/IDs and route behavior while reducing duplicated template code.

3. **Shared Patient Form Sync Script**
- Added new shared JS helper: `static/js/patient_form.js` with `initPatientTypeSync(...)`.
- Replaced duplicated patient type/treatment track sync logic in both add/edit templates with shared helper usage.
- Kept diagnosee questionnaire visibility behavior in add form via callback hook.

4. **Debug / Verification**
- Focused route checks:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest -v tests.test_app.ClinicTestCase.test_add_patient tests.test_app.ClinicTestCase.test_patient_detail_sections_render tests.test_app.ClinicTestCase.test_crm_patient_view_shows_all_and_candidates_buttons`
- Full regressions:
  - `SECRET_KEY=test-secret-key WTF_CSRF_ENABLED=False /usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'`
- Root module regressions:
  - `/usr/bin/python3 -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

**Date:** 2026-04-30

**Objective:** Fix recurring calendar edit flow where saving with scope (`this and upcoming` / `all in series`) could appear to do nothing.

**Release Summary:**

1. **Root Cause Fixed (Recurring Edit Scope Save)**
- In `openAppointmentEditor`, the scope picker reused the same modal body and replaced edit fields before payload creation.
- Save logic then attempted to read removed DOM nodes (`editMeetingDate`, `editMeetingTime`, etc.), causing payload build failure and no outgoing update request.

2. **Implementation Update**
- Added an edit snapshot in `submitAppointmentEdit()` before opening scope selection.
- Payload builder now uses snapshot values rather than querying DOM after scope modal render.
- Added guard for missing edit controls and fallback `showActionModal` error handling if payload build fails.
- Added catch handling on the scope promise chain to surface errors instead of silent no-op behavior.

3. **Validation**
- Full suites passed:
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 58

**Date:** 2026-04-30

**Objective:** Improve intake editing safety and usability with local draft autosave and unsaved-change protection.

**Release Summary:**

1. **Intake Draft Autosave**
- Added client-side autosave for intake form fields (`intake_*`) to local storage every 20 seconds while changes are pending.
- Added draft status indicator in the intake footer.

2. **Draft Restore Flow**
- On intake tab load, if a local draft exists, clinicians are prompted to restore it.
- On successful form submit, the local draft is cleared automatically.

3. **Unsaved-Change Guard**
- Added browser leave warning when intake changes are unsaved.
- Added visual unsaved-changes status feedback while editing.

4. **Validation**
- Targeted intake tests passed:
  - `python -m unittest -v tests.test_app.ClinicTestCase.test_intake_form_save_edit_and_export_docx tests.test_app.ClinicTestCase.test_intake_partial_update_preserves_existing_fields tests.test_app.ClinicTestCase.test_legacy_plain_text_intake_can_be_loaded_edited_and_exported`
- Full regressions passed:
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 57

**Date:** 2026-04-30

**Objective:** Complete intake regression debug pass, add missing partial-update protection test coverage, and prepare a clean merge-ready patch set.

**Release Summary:**

1. **Intake Partial-Update Data Safety (Backend)**
- Confirmed and validated merge-safe intake updates in `update_patient_info` + `intake_data_from_request`.
- Partial submissions now preserve untouched `intake_*` fields by merging request payload with parsed existing questionnaire state.

2. **Intake Multi-Section Editing UX (Frontend)**
- Verified the new intake section tabs and pane-switch behavior in patient detail view.
- Verified DOCX export remains directly accessible from intake panel.

3. **New Regression Test Added**
- Added: `test_intake_partial_update_preserves_existing_fields` in `tests/test_app.py`.
- This specifically guards against the original regression where partial saves could clear unposted intake fields.

4. **Validation**
- Targeted intake tests:
  - `python -m unittest -v tests.test_app.ClinicTestCase.test_intake_form_save_edit_and_export_docx tests.test_app.ClinicTestCase.test_intake_partial_update_preserves_existing_fields tests.test_app.ClinicTestCase.test_legacy_plain_text_intake_can_be_loaded_edited_and_exported`
- Full regressions:
  - `python -m unittest discover -s tests -p 'test_*.py'` → 162 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

5. **Merge Readiness Cleanup**
- Removed transient `clinic.db` binary diff from working tree.
- Remaining intentional changes are limited to:
  - `app.py`
  - `templates/patient_detail.html`
  - `tests/test_app.py`

---

## Session 56

**Date:** 2026-04-18

**Objective:** Upgrade manual Google Docs `Sync Now` to true live progress, keep test compatibility, validate behavior end-to-end, and record a focused security review.

**Release Summary:**

1. **True Live `Sync Now` Progress (Admin Profile)**
- Replaced timer-based client progress with real backend job progress.
- Added async manual sync execution with in-memory job tracking.
- Added polling endpoint for progress/status retrieval.
- Progress now reflects actual processed targets (processed/total, current target, percent).

2. **Backend Manual Sync Job API**
- Updated `/admin/google-docs/auto-sync-now` to start a background sync job in normal runtime.
- Added `/admin/google-docs/auto-sync-status/<job_id>` for progress polling.
- Added bounded job retention and single-active-job protection to avoid overlapping manual runs.

3. **Sync Runner Progress Emission**
- Extended `_run_google_docs_auto_sync(...)` with an optional progress callback.
- Emitted phase/status updates across preparation, per-target processing, and completion.
- Included `targets_total` and `targets_processed` in sync result payloads.

4. **Compatibility Fix for Tests**
- Preserved synchronous manual sync behavior when `TESTING=True`.
- This keeps existing integration tests stable (status code and DB-write behavior).

5. **Validation**
- Verified suites:
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v tests.test_security`

6. **Security Review Snapshot (Static + Tests)**
- Confirmed existing protections still pass current security tests (auth, TOTP flow, inactivity timeout, path traversal check).
- Flagged high-priority hardening items for next iteration:
  - Replace default fallback `SECRET_KEY='dev'` in non-dev runtime.
  - Remove hard-coded default admin credentials from bootstrap/migration path.
  - Add stricter webhook request verification (`/api/gdoc/webhook`) beyond header presence.

---

## Session 55

**Date:** 2026-04-17

**Objective:** Expand Google Docs automation to production-ready scheduling with per-target sync modes, retries, history, and health visibility.

**Release Summary:**

1. **Per-Target Auto-Sync Modes**
- Extended auto-sync target config to support per-target mode selection.
- Patient targets remain pull-only.
- Group targets now support:
  - `Pull doc to site only`
  - `Pull and push (two-way)`

2. **Sync Retry/Backoff + Partial Result Handling**
- Added transient-error detection and retry/backoff for Google Docs sync operations.
- Manual auto-sync responses now include run status, push counts, warnings, and history id.
- Partial failures no longer silently pass; they are surfaced as warnings/errors.

3. **Sync History/Audit Trail**
- Added `gdocs_sync_history` table and write path for auto, request-triggered, worker-triggered, and manual runs.
- Added Admin Profile history table with run time, trigger, status, processed targets, synced count, and error count.

4. **Background Scheduler Worker**
- Added a daemon background worker loop for recurring auto-sync execution independent of incoming requests.
- Worker starts in non-testing mode during initialization.

5. **Dashboard Health Indicator**
- Added Google Docs auto-sync health widget to Admin Dashboard.
- Shows enabled/disabled state, interval, selected docs count, last run, next run, overdue flag, and last status.

6. **Compatibility + Stability**
- Added graceful fallback for environments/tests where legacy schemas are missing Google Docs columns.
- Updated `schema.sql` baseline with `gdocs_sync_history` for clean installs.

7. **Validation**
- Verified tests:
  - `/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'`
  - `/usr/bin/python3 -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 54

**Date:** 2026-04-16

**Objective:** Improve group meeting record UX and parser output quality, and ensure copied questionnaire sheet tabs keep original names.

**Release Summary:**

1. **Group Previous-Meeting Edit UX**
- Updated group session cards so the edit panel is hidden by default.
- When pressing `Edit Record`, the edit panel now replaces the read-only summary block instead of showing as a duplicate second box.
- This removes the always-visible extra panel (`Session Status` + members table) until edit mode is explicitly opened.

2. **Group Content Parsing Cleanup**
- Updated Hebrew section parser to keep only the actual content body after the `תוכן` / `Content` marker.
- Dropped structured marker lines (`|משתתפים`, `|חסרים`, `|תוכן`, and variants) from parsed content.
- Updated group pull processing so saved `session_summary` stores the cleaned content text, not the section-marker scaffold.

3. **Questionnaire Sheet Copy Naming**
- Updated questionnaire tab copy flow (new file creation and update flow) to rename copied sheets to the exact source tab name.
- Prevents Google default `Copy of ...` tab names; resulting tabs now keep original names like `PCL-5`.

4. **Validation**
- Verified Python compilation:
  - `python -m py_compile app.py scripts/google_docs.py`
- Verified focused parser/group-doc tests:
  - `python -m unittest tests.test_google_docs_integration` → 10 tests passed
- Verified full test coverage:
  - `python -m unittest discover -s tests -p 'test_*.py'` → 153 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

---

## Session 53

**Date:** 2026-04-16

**Objective:** Improve questionnaire-tab behavior when Google Sheets API is disabled so admins get actionable guidance instead of raw HttpError output.

**Release Summary:**

1. **Error Normalization for Sheets Calls**
- Added Google Sheets error parsing helpers to detect API-disabled and scope issues.
- Replaced raw exception dumps with clear, user-facing guidance (for example: API disabled for connected project).

2. **Actionable UI in Questionnaire Tab**
- Added direct `Enable Sheets API` button when an activation URL is present in the error.
- Added `Open Source Spreadsheet` button in source-load failure state for quick verification of the configured source sheet.
- Applied the same activation-link behavior for linked-file questionnaire tab loading errors.

3. **Validation**
- Verified Python compilation:
  - `python -m py_compile app.py`
- Verified tests:
  - `python -m unittest discover -s tests -p 'test_*.py'` → 153 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

---

## Session 52

**Date:** 2026-04-16

**Objective:** Fix diagnosee Questionnaire tab so admins can see and use questionnaire checkboxes even when no patient questionnaires file is linked yet.

**Release Summary:**

1. **Root Cause + Data Flow Fix**
- The Questionnaire tab previously showed only linked-file data and did not expose a checkbox selection flow on the patient detail page.
- Added source questionnaire loading in patient detail so checkbox options are rendered from the configured source Google Sheet tabs.

2. **Visual + Functional Fix in Questionnaire Tab**
- Added checkbox list (`Select Questionnaires`) directly in the dedicated Questionnaire tab.
- Added submit flow that:
  - creates and links the patient questionnaires file when missing, or
  - copies selected source tabs into the existing linked patient file (without duplicating already-existing tabs).
- Added clear warning blocks when source spreadsheet loading fails.

3. **Backend Route + Sync Handling**
- Added patient route for questionnaire saves/updates:
  - `POST /patient/<id>/save_questionnaires`
- Saves selected questionnaire metadata and reports copied/skipped/missing tab counts via flash messages.

---

## Session 51

**Date:** 2026-04-16

**Objective:** Fix diagnosee Questionnaire tab so linked Google Sheets questionnaires are visible in the dedicated tab view.

**Release Summary:**

1. **Questionnaire Tab Data Fix (Diagnosee View)**
- Updated patient-detail backend flow to fetch visible sheet tab names directly from the linked questionnaires spreadsheet (`questionnaires_file_id` / `questionnaires_file_url`).
- Kept safe fallback to stored `questionnaires_selected` data when live tab loading is unavailable.

2. **Visual/UI Fix in Dedicated Questionnaire Tab**
- Added an `Available Questionnaires` section that renders live tab badges in the dedicated Questionnaire tab.
- Added a non-blocking warning message when Google tab loading fails, so admins can see why list loading failed instead of seeing an empty panel.
- Preserved `Selected During Setup` display when it differs from currently available tabs.

3. **Validation**
- Verified Python compilation:
  - `python -m py_compile app.py`
- Verified tests:
  - `python -m unittest discover -s tests -p 'test_*.py'` → 153 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

---

## Session 50

**Date:** 2026-04-16

**Objective:** Make questionnaires discoverable and controllable through a dedicated Questionnaire tab/button, with diagnosee auto-enable and intake-style quick-action enablement for other patients.

**Release Summary:**

1. **Dedicated Questionnaire Navigation + View**
- Added a dedicated Questionnaire button next to Intake in patient detail tabs.
- Moved questionnaire-specific UI out of the Intake panel into its own Questionnaire tab panel.
- Questionnaire tab now shows linked file access and selected questionnaire badges in a dedicated section.

2. **Enablement Rules (Diagnosee + Manual Quick Action)**
- Added `has_questionnaire_tab` patient flag and backend handling so Questionnaire visibility is explicit.
- Diagnosee patients now auto-enable the Questionnaire tab on create/edit.
- Added admin quick action to manually enable the Questionnaire tab for any patient (similar to Intake behavior).
- Added backend route to persist quick-action enablement and redirect directly into the Questionnaire tab.

3. **Spelling + Consistency Fixes**
- Corrected questionnaire spelling in touched UI/settings labels and generated spreadsheet naming.
- Updated schema baseline to include `has_questionnaire_tab` so fresh installs are consistent without relying only on runtime migrations.

4. **Validation**
- Verified Python compilation:
  - `python -m py_compile app.py scripts/import_clinic_data.py scripts/export_data.py test_import_clinic_data.py test_export_data.py test_google_calendar.py`
- Verified tests:
  - `python -m unittest discover -s tests -p 'test_*.py'` → 153 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

---

## Session 49

**Date:** 2026-04-16

**Objective:** Finalize group-note parsing for the updated Hebrew format and add diagnosee questionnaire sheet generation from a configurable Google Sheets source file.

**Release Summary:**

1. **Group Meeting Parsing + Matching Update**
- Updated the Google Docs parser to support the new header format such as `פגישה # 13/04/2026` while keeping support for existing `פגישה 6- 23/02/26` style headers.
- Section parsing now recognizes `משתתפים`, `חסרים`, and `תוכן` markers more robustly (including variants like trailing `:`) and keeps content strictly from the `תוכן` section when structured headers are present.
- Pull sync now prefers matching sessions by parsed meeting title first, then date/ordinal fallback, and writes the parsed meeting title into the group session title field.
- Missing-member reason extraction now correctly captures reason text after `-`, `—`, or `:` in the `חסרים` section.

2. **Diagnosee Questionnaire Sheet Flow**
- Added admin-configurable setting: questionnaires source Google Sheets link in Admin Profile (`Specify questionnaires Google Sheets file link`).
- Added backend helpers to:
  - read questionnaire tab names from the source spreadsheet,
  - create a diagnosee spreadsheet named `<Diagnosee Name> questionnaires`,
  - copy selected questionnaire tabs into that new spreadsheet.
- Added diagnosee questionnaire selection UI in Add Patient (checkboxes + sync button pulling current tabs from the source sheet).
- On diagnosee creation, selected questionnaires now trigger spreadsheet creation and store the generated file link/id on the patient record.
- Added a linked questionnaires file block in the patient intake view for quick opening.

3. **Google Permissions + Schema**
- Added Google Sheets OAuth scope to calendar integration scopes for questionnaire operations.
- Added patient columns for questionnaire integration metadata (`questionnaires_file_id`, `questionnaires_file_url`, `questionnaires_selected`).
- Added compatibility defaults in patient-detail rendering for legacy rows.

4. **Validation**
- Parser verified against uploaded `תיעוד קבוצת פסיכותרפיה.docx` (10 meeting blocks parsed).
- Verified new-format sample parsing for `פגישה # dd/mm/yyyy` with correct participants/missing/content extraction.
- Verified Python compilation:
  - `/usr/bin/python3 -m py_compile app.py scripts/google_docs.py scripts/google_calendar.py`
- Verified tests:
  - `/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'` → 153 tests passed
  - `/usr/bin/python3 -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

---

## Session 48

**Date:** 2026-04-15

**Objective:** Fix Hebrew group Google Docs parsing so each meeting block is split correctly into participants, missing, and content for real-world templates like `~פגישה 5- 16/02/26`.

**Release Summary:**

1. **Structured Hebrew Group Parsing**
- Updated the group parser to split each session block by section headers:
  - `|משתתפים` -> parsed `participants`
  - `|חסרים` -> parsed `missing`
  - `|תוכן` -> parsed `content`
- Kept support for the meeting identifier style with tilde and dash date, for example `~פגישה 9- 30/03/26`.

2. **Two-Meeting Block Handling**
- Verified and fixed multi-meeting extraction so consecutive Hebrew blocks are parsed as separate sessions (for example meeting 9 and meeting 10 in one document).
- Pull sync now updates the matching group sessions with structured summary content and applies parsed attendance signals where names are matched.

3. **Validation**
- Added regression coverage for the two-meeting Hebrew example structure.
- Verified with tests:
  - `python -m unittest tests.test_google_docs_integration` -> 10 tests passed
  - `python -m unittest discover -s tests -p 'test_*.py'` -> 153 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` -> 13 tests passed

---

## Session 47

**Date:** 2026-04-15

**Objective:** Improve editing flow and layout by locking non-primary sections by default, fixing group page structure issues, and splitting group Google Docs actions into explicit append vs pull/replace operations.

**Release Summary:**

1. **Default Minimized Panels + Edit Locks**
- Updated group and patient detail screens so secondary panels start minimized while the primary working area remains visible.
- Locked key text/date editing fields by default and added explicit `Edit / Cancel / Save` flows before changes can be submitted.
- Added lock-first editing for group member history date rows so former members' start/end dates are only editable when intentionally opened.

2. **Group Meeting Layout + Duplicate Header Fix**
- Reordered session summary presentation to prioritize full-width content, then participants and missing lists.
- Removed the repeated previous-meeting title effect on expanded past sessions while keeping action controls available.

3. **Google Docs Integration Split (Group)**
- Added explicit group routes:
  - `POST /groups/<id>/push-gdoc` (append-only, supports optional `session_id`)
  - `POST /groups/<id>/pull-gdoc` (pull from docs and replace matching site records)
- Kept `POST /groups/<id>/sync-gdoc` backward-compatible and mode-aware (`both`, `pull`, `push`).
- Reworked group UI controls into two clear actions:
  - append site notes to the doc (with warning)
  - pull doc notes and replace site records.

4. **Validation**
- Updated and expanded automated tests for the new Docs action split and updated labels.
- Full automated suite passed:
  - `python -m unittest discover -s tests -p 'test_*.py'` → 152 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

---

## Session 46

**Date:** 2026-04-14

**Objective:** Improve the group Google Docs parser so it can reliably identify real Hebrew session headers and sync those structured notes into the correct meeting history.

**Release Summary:**

1. **Hebrew Group Header Recognition**
- Added support for real-world Hebrew session headers such as:
  - `~פגישה 6- 23/02/26`
  - `פגישה #6- 23/02/26`
- The parser now accepts the leading tilde marker and common dash variants used in manually written Google Docs.

2. **Structured Hebrew Content Sync**
- Preserved Hebrew section blocks like `|משתתפים`, `|חסרים`, and `|תוכן` so they are pulled into the linked group session summary without losing structure.
- Matching group meetings now update correctly by the parsed meeting date and flow into the session history.

3. **Validation**
- Added regressions for the Hebrew tilde-header format and for syncing those notes into the matching group meeting record.
- Verified with automated tests:
  - `python -m unittest tests.test_google_docs_integration` → 8 tests passed

---

## Session 45

**Date:** 2026-04-14

**Objective:** Finish the requested profile/settings polish by stabilizing filters, adding collapsible admin/calendar panels, enabling patient photos, introducing a public About page, tightening header responsiveness, and improving resource access control.

**Release Summary:**

1. **UI + Responsive Polish**
- Slimmed the top ribbon/navigation so it stays out of the way more reliably on smaller windows.
- Stabilized the quick-filter buttons so selecting All no longer changes the box size or creates a jarring bold-state jump.
- Made the calendar right-side panels collapsible from their headers for a cleaner workflow.

2. **Admin Profile + Public About Page**
- Reworked the admin profile so the first card stays open while the other sections can be expanded on demand.
- Added editable About-page settings for clinic contact phone, email, summary text, map link, and a public on/off toggle.
- Added a new public About page plus preview access for the admin.

3. **Patient Photos + Resource Permissions**
- Added patient profile picture upload support and surfaced the avatar across the CRM roster, patient detail view, and patient portal.
- Expanded resource management with explicit patient view/download permissions and enforced those rules in the public/patient resource links.

4. **Translation Cleanup**
- Localized the newly touched login, profile, resources, and About-page text into Hebrew so the experience is more consistent across screens.

5. **Validation**
- Added focused regressions for About-page settings, patient photo upload, and resource visibility rules.
- Full automated suite passed:
  - `python -m unittest discover -s tests -p 'test_*.py'` → 149 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

---

## Session 44

**Date:** 2026-04-14

**Objective:** Repair the full Google Docs workflow for groups and individual treatment, including disconnect behavior, multi-meeting parsing, pull sync reliability, and stable filter-button visuals.

**Release Summary:**

1. **Group Google Docs Disconnect + Sync Fix**
- Verified and fixed the group disconnect flow so a connected group doc can be removed cleanly.
- Upgraded the group sync action to pull structured meeting content from Google Docs into matching group sessions and then push unsynced meeting records back when needed.
- Added visible status feedback so the group page now shows when sync is running, succeeds, or fails.

2. **Individual Treatment Docs Reliability**
- Re-verified patient Google Docs connect, disconnect, and sync flows.
- Kept the multi-meeting parser working across separate session blocks so treatment notes can still be pulled correctly into the individual record.

3. **Design Stability**
- Stabilized the All and Candidates filter buttons so switching states no longer causes the control box to jump in size or break the visual flow.

4. **Validation**
- Added focused regressions for patient disconnect, group disconnect, multi-meeting parsing, and pulling group summaries from Google Docs.
- Full automated suite passed:
  - `python -m unittest discover -s tests -p 'test_*.py'` → 145 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

---

## Session 43

**Date:** 2026-04-14

**Objective:** Fix category counters so they match the real patient totals and harden the group Google Docs sync workflow with visible progress feedback and dependency checks.

**Release Summary:**

1. **Patient Counter Alignment**
- Fixed the CRM category totals so the visible All and Candidates counts now match the actual patient roster.
- Corrected the waiting/candidate mapping in the counter payload and aligned the All filter to the true filtered total.

2. **Group Docs Sync Reliability**
- Verified the Sync to Docs backend route with automated coverage.
- Added a visible sync status indicator on the group page so admins can see when syncing is in progress, succeeds, or fails.
- Hardened the Google dependency checks so missing libraries now return a clear install hint instead of crashing the route.

3. **Validation**
- Added focused regressions for counter accuracy and group Docs sync success.
- Full automated suite passed:
  - `python -m unittest discover -s tests -p 'test_*.py'` → 142 tests passed
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar` → 13 tests passed

---

## Session 42

**Date:** 2026-04-14

**Objective:** Make the requested group Docs integration control and patient-view candidate filters clearly visible in the actual screens the admin uses.

**Release Summary:**

1. **Group Page Visibility Fix**
- Added a persistent Google Docs Integration button in the group header so the integration is visible even before a doc is linked.
- Kept the Sync to Docs action available once a group doc is attached.

2. **Patients View Quick Filters**
- Added visible All and Candidates quick-filter buttons directly to the CRM patient view.
- This makes candidate filtering available in the main patient roster, not only inside the notifications chooser.

3. **Validation**
- Added focused regressions for the visible group integration button and the CRM All/Candidates quick filters.
- Verified the visibility fixes with automated tests before publish.

---

## Session 41

**Date:** 2026-04-14

**Objective:** Expose group meeting Docs sync controls, improve notification patient filtering, and make upcoming appointments visible in patient-facing views.

**Release Summary:**

1. **Group Meeting Docs Sync**
- Added a visible Sync to Docs action in the group Google Docs area and directly on meeting cards.
- Added a backend sync endpoint so linked group meeting records can be pushed into the shared Google Doc.

2. **Candidate Filter in Notification Targeting**
- Added quick filter buttons in the selected-patients chooser so admins can switch between all patients and candidates more easily.
- Kept bulk select and clear actions available while filtering only the visible list.

3. **Patient Upcoming Meetings Fix**
- Updated patient upcoming-event logic so group meetings now appear alongside regular appointments.
- The next-meeting banner and patient detail next-appointment summary now surface the soonest scheduled event more reliably.

4. **Validation**
- Added focused regressions for the new group Docs sync button, candidate filtering, and patient upcoming group-session visibility.
- Full automated suite passed:
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 40

**Date:** 2026-04-14

**Objective:** Finish the patient notification seen-state flow, add Google Docs controls inside group management, and stabilize the group meeting content view.

**Release Summary:**

1. **Patient Notification Seen-State**
- Added a dedicated read-state endpoint so patient and admin notifications can be marked as seen explicitly.
- Updated the bell offcanvas so notifications stay visible until the user chooses to mark one or all of them as seen.

2. **Group Google Docs Integration**
- Added group-level Google Docs linking, attaching, opening, and detaching routes.
- Exposed the controls directly in the group management view so each group can keep a shared working document.

3. **Group View Stability**
- Simplified the group management panel behavior so content stays open reliably instead of briefly flashing and collapsing.
- Replaced the unstable Bootstrap collapse flow in patient meeting logs and past group meetings with a plain persistent toggle pattern.
- Added a protective style override so remaining expandable sections stay visible when opened.

4. **Validation**
- Added focused regressions for notification seen-state and group Google Docs rendering.
- Full automated suite passed:
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 39

**Date:** 2026-04-14

**Objective:** Restore the admin sidebar reliably across window sizes, add targeted bell-notifications, and strengthen the group meeting recording workflow.

**Release Summary:**

1. **Responsive Sidebar Rework**
- Replaced the fragile sidebar toggle behavior with a simpler CSS-driven responsive pattern.
- Desktop now keeps the side menu visible again, while smaller windows use a stable slide-in menu with backdrop and Escape handling.

2. **Bell Notification Center for Admin + Patients**
- Added a dedicated notification center behind the bell icon.
- Admins can now post notifications to all patients, all group patients, all private patients, all residency patients, or selected patients from a checklist.
- Patients can open the bell area to view received notifications, and new notifications also surface through toast alerts.

3. **Group Session Integration Upgrade**
- Fixed the session-member attendance payload path so the group detail view no longer breaks.
- Group session records now auto-structure the summary into Meeting / Participants / Missing / Content format.
- Attendance and content are shown directly on each session card, and patient notes are kept aligned with present/missed statuses.

4. **Validation**
- Added focused regressions for targeted notifications and structured group session summaries.
- Full automated suite passed:
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 38

**Date:** 2026-04-14

**Objective:** Clean up oversized demo data, repair responsive admin navigation, compact the dashboard layout, and improve calendar follow-up usability.

**Release Summary:**

1. **Demo Data Reset + Group Coverage**
- Replaced the 10,000-candidate demo dataset with a compact sample set covering private, residency, group, intake, and diagnosee workflows.
- Extended the reset utility to also clear and reseed group-related tables.
- Added a sample therapy group with membership and sessions so group flows are visible during QA.

2. **Responsive Sidebar Reliability**
- Hardened the mobile/partial-width admin sidebar so hidden panels no longer intercept clicks or obscure page content.
- Added close-on-backdrop, close-on-link-tap, and Escape-key behavior for smoother navigation on smaller windows.

3. **Dashboard Density Improvements**
- Tightened spacing and rebalanced dashboard columns/cards to reduce unnecessary empty space and keep the admin summary view compact.

4. **Calendar Follow-Up Overflow Control**
- Capped initial follow-up indicators to five items and added a Show more / Show less toggle for additional entries.
- Kept week navigation controls in stable LTR order so Hebrew mode arrows are no longer visually flipped.

5. **Validation**
- Focused regression checks passed for the calendar follow-up control, Hebrew week nav, and compact sample reset.
- Full automated suite passed:
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 37

**Date:** 2026-04-13

**Objective:** Allow admins to attach external document/website links in clinical notes and medical history entries.

**Release Summary:**

1. **Meeting Log Link Support**
- Added `link_url` support to meeting logs (`notes`) in both schema and runtime migrations.
- Updated add/edit note routes to persist optional link URLs.
- Updated notes UI to include a URL field and render a clickable "Open Link" action per note.

2. **Encounter Note Link Support (Medical History)**
- Added `link_url` support to encounter notes (`patient_logs`) in both schema and runtime migrations.
- Updated encounter log creation route to save optional link URLs.
- Updated encounter note UI to include a URL field and render a clickable "Open Link" action per entry.

3. **Validation**
- Tested via full automated suite:
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 36

**Date:** 2026-04-12

**Objective:** Reinstate language switching UX, add standalone encounter notes, improve sidebar responsiveness on smaller windows, strengthen restricted-network compatibility, and add test-patient reset tooling.

**Release Summary:**

1. **Language Switching Restored + Expanded**
- Reintroduced the language-toggle control in the admin sidebar.
- Localized additional system labels in the messages offcanvas and interaction text.
- Added new Hebrew translation keys for the newly introduced UI strings.

2. **Patient Encounter Notes (Side-by-Side with Treatment Logs)**
- Added `patient_logs` storage (migration + schema support).
- Added admin routes to add/delete encounter notes.
- Updated patient detail notes tab to show treatment meeting logs and encounter notes side-by-side.
- Encounter notes now support date, title, and free-form content for non-session interactions.

3. **Sidebar Collapse Responsiveness Fix**
- Fixed mobile/partial-width sidebar toggle state detection logic in the admin shell.
- Sidebar now opens/closes reliably outside full-screen widths with backdrop state handling.

4. **Test Patient Reset Utility**
- Added admin-only `reset_test_patients` action to replace existing patient data with a compact test set.
- Seeded set includes one patient per key status/type-track profile and sample treatment methods for verification workflows.

5. **Restricted-Network Hardening (Fortinet-Friendly)**
- Vendored key frontend assets locally under `static/vendor/`:
  - Bootstrap CSS/RTL + JS bundle
  - Bootstrap Icons + fonts
  - FullCalendar JS
  - Tailwind runtime script
- Updated layout to load these local assets instead of external CDN links.

6. **Copy/Paste Enablement**
- Added explicit selectable-text CSS rules across app shell and form controls.
- Added runtime cleanup for legacy inline clipboard-blocking attributes (`oncopy/onpaste/oncut`) to ensure copy/paste remains available.

7. **Validation**
- Full automated tests passed:
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 35

**Date:** 2026-04-12

**Objective:** Complete dashboard/CRM redesign adjustments, normalize patient lifecycle rules, repair patient detail experience, and finalize admin shell/mobile behavior.

**Release Summary:**

1. **Dashboard Simplification + Collapsible Panels**
- Removed the top-level all-patients metric from the admin dashboard summary strip.
- Converted major dashboard cards into collapsible sections using semantic details/summary containers.
- Adjusted panel/card sizing to reduce visual width and improve readability.

2. **Status Normalization (Waiting -> Candidate)**
- Added canonical status normalization so waiting and waiting for scheduling are treated as candidate.
- Applied normalization in create/edit flows and CRM/dashboard filtering logic.
- Added migration-time data normalization to convert legacy waiting records to candidate.

3. **Patient Type/Treatment Track Flow Update**
- Updated add/edit patient forms to keep billing type as private/residency.
- Moved group/initial-intake/diagnosee selection into treatment-track behavior while preserving existing logic paths.
- Kept intake-related behavior active for intake/diagnosee tracks.

4. **CRM + Table/Filter Behavior Corrections**
- Updated CRM labels and status rendering to consistently show candidate.
- Fixed duplicate-id issue in cards container markup that could affect view/filter behavior.
- Refined summary cards layout sizing and responsive behavior.

5. **Patient Detail Page Repair**
- Rebuilt patient detail structure with stable tab-driven sections: overview, meeting logs, billing, messages, supervision, and intake (when enabled).
- Restored Google Docs actions (create/attach/open/sync/detach) in-page.
- Fixed messaging area layout so it no longer blocks page content on desktop/mobile.
- Preserved legacy test anchors required by existing automated checks.

6. **Admin Shell + Login/2FA UX**
- Removed language switch action from top admin bar.
- Made admin name/avatar in top bar clickable to profile.
- Removed redundant admin entry from side menu.
- Added mobile sidebar toggle/backdrop handling for non-fullscreen and mobile widths.
- Kept admin 2FA flow as step-gated after username/password verification and removed legacy inline OTP field from initial login form.

7. **Responsiveness and Styling**
- Added dashboard fold styling and patient-detail overflow safeguards.
- Improved mobile behavior for message thread, panel stacking, and header/sidebar interaction.

8. **Validation**
- Full automated tests passed:
  - `python -m unittest discover -s tests -p 'test_*.py'`
  - `python -m unittest -v test_export_data test_import_clinic_data test_google_calendar`

---

## Session 34

**Date:** 2026-04-09 08:10

**Objective:** Performance optimization for group sessions updating logic.

**Release Summary:**
- **Performance:** Replaced an N+1 looping `db.execute` construct in the `api_update_group_session` route (`app.py`) with a single batch `db.executemany` statement. This significantly improves database write performance when updating multiple recurring group session rows simultaneously.

## Test API Treatment Method Options Get

**Date:** April 09, 2026

**Objective:** Add a unit test for the `/api/treatment_method_options` GET endpoint.

**Release Summary:**
- Wrote a new test `test_api_treatment_method_options_get` in `test_app.py`.
- Tested the endpoint for correct unauthenticated redirects, patient 403 authorization failures, and successful 200 JSON payload responses for admins.
- Addressed test errors related to schema mismatch and role validation mismatch.
---

## Session 33

**Date:** April 4, 2026

**Objective:** CRM patient list redesign — treatment method tagging, table/cards view toggle, drag-to-reorder, cleaner badges, and treatment method filter.

**Release Summary:**

1. **Treatment Method Tag**
- Added `treatment_method TEXT` column to `patients` table via DB migration.
- Added `sort_order INTEGER` column to `patients` table for manual drag order.
- Added `treatment_method_options` table, seeded with: Psychodynamic, CBT, EFT, Management, 15 sessions, 3 sessions.
- Treatment method select field added to `add_patient` and `edit_patient` forms.

2. **CRM Filter Enhancement**
- `fetch_patients_by_status` now accepts a `treatment_method` filter parameter.
- Added `manual_order` sort option (by `sort_order` column, fallback to `created_at DESC`).
- Filter panel auto-expands when any active filter is set.
- Clear-filters button (×) added alongside Apply button.
- Patient count shown in the section header.

3. **CRM Table View**
- New `<table>` layout with columns: Name, Status, Type, Method, Next Appt, action button.
- Color-coded status dot (green/amber/grey) instead of text badge.
- Drag handle column visible only when `sort=manual_order` is active.
- Row click navigates to patient detail.

4. **CRM Cards View**
- Responsive CSS grid of compact patient cards (`crm-cards-grid`).
- Shows: name, self-booking icon (only when enabled), status dot, type badge, treatment method badge, next appointment, unread message count.

5. **View Toggle (Table ↔ Cards)**
- Toggle buttons in the toolbar switch between table and cards views.
- Preference persisted in `localStorage` across page loads.

6. **Drag-to-Reorder**
- SortableJS loaded from CDN only when `sort=manual_order` is active.
- Dragging rows (table) or cards saves order via `POST /api/patients/reorder`.
- Drag handle cursor on table rows; free-drag on cards.

7. **Badge & Display Cleanup**
- Removed patient `#id` number from all CRM rows.
- Removed "Self-booking OFF" badge; self-booking shown only as a small calendar ✓ icon when enabled.
- Add Patient shortcut button added to CRM header.

8. **New API Endpoints**
- `POST /api/patients/reorder` — saves drag-and-drop sort order.
- `GET /api/treatment_method_options` — lists current treatment method options.
- `POST /api/treatment_method_options` — adds a new option.
- `DELETE /api/treatment_method_options/<id>` — removes an option.

9. **CSS Additions** (`static/style.css`)
- `.crm-filter-grid`, `.crm-view-btn`, `.crm-status-dot`, `.crm-type-badge`, `.crm-method-badge`
- `.crm-table-wrap`, `.crm-table`, `.crm-table-row`, `.crm-drag-handle`
- `.crm-cards-grid`, `.crm-patient-card`, `.crm-card-header`, `.crm-card-name`, `.crm-card-appt`

10. **Test Coverage**
- All 64 existing tests pass with no regressions.
- New features verified via targeted integration checks (migration, filter, sort, all API endpoints, CRM page render).

---

## Session 32

**Date:** April 2, 2026

**Objective:** Finalize calendar recurrence correctness, improve treatment-log editing ergonomics, enforce Hebrew textbox alignment, disable non-login autofill, move inactivity timeout to 5 minutes, and strengthen patient background summaries from prior notes.

**Release Summary:**

1. **Calendar Recurrence Reliability (Edit/Delete)**
- Removed duplicate recurrence scope selection from the recurring edit modal.
- Kept a single clear scope-choice dialog at action time for recurring edit and recurring delete.
- Hardened `scope=upcoming` update logic so split recurring rows in the same series are consistently truncated/deleted from the selected occurrence onward.
- Implemented `scope=all` update behavior over the full recurrence group (not only one anchor row), including conflict checks and consistent time/day updates.

2. **Regression Coverage Expanded**
- Added test ensuring recurring `scope=all` update correctly updates all split rows in the recurrence group.
- Existing recurring one/upcoming/delete tests continue passing.

3. **Treatment Log Editing UX**
- Expanded treatment-log current meeting content input to full width in the add-note form.
- Increased textarea height for both add-note and edit-note content fields for easier long-form writing.

4. **Hebrew Textbox Alignment Across Site**
- Added global RTL form-control/textbox alignment rules for `input`, `textarea`, and `select` elements (excluding non-textual control types).
- Ensures right-aligned editing experience throughout Hebrew UI pages.

5. **Autofill Policy (Login-Only Exception)**
- Added global frontend guard that disables browser autocomplete/autocorrect/autocapitalize/spellcheck on non-login pages.
- Login endpoint is explicitly excluded so credential/OTP helper behavior remains available there.

6. **Inactivity Timeout Policy Updated**
- Changed default inactivity timeout to **5 minutes** (config + enforcement fallback).
- Updated inactivity-related tests to match the new 5-minute policy.

7. **Patient Background Suggestion Quality**
- Improved `build_patient_background_from_notes` output into a clearer structured clinical summary style.
- Added extraction of key summary points from recent/important note segments.
- Summary now emphasizes timeline, recurring patterns, current focus, and concise clinical takeaway based on historical entries.
- Added regression test validating structured summary sections are produced from note history.

**Validation & Debugging:**

1. Ran full automated test suite:
- `python test_app.py`
- Result: **59 tests passed**.

2. Verified no recurrence regressions in recurring edit/delete flows through existing and newly added tests.

**Files Modified:**
- `app.py`
- `templates/calendar.html`
- `templates/patient_detail.html`
- `templates/layout.html`
- `static/style.css`
- `test_app.py`
- `CHANGES.md`

---

## Session 30

**Date:** March 22, 2026

**Objective:** Fix recurring deletion behavior, finish profile localization, redesign groups manager flow, simplify calendar block handling, and normalize meeting data.

**Release Summary:**

1. **Recurring Delete Reliability Fixed**
- Added `appointments.recurrence_group_id` with migration/index support.
- Added grouping helpers to attach legacy recurring rows to stable logical series.
- Updated recurring create/split/update paths to preserve group identity.
- Fixed delete scope behavior so:
  - `all` removes the whole logical recurring series,
  - `upcoming` truncates and/or removes the correct related recurring rows.

2. **Regression Coverage Added**
- Extended tests for recurring series deletion edge-cases:
  - split recurring anchors without preexisting group ids,
  - upcoming-scope truncation across related anchors.
- Full suite verification passed: `python test_app.py`.

3. **Profile Hebrew Localization Completed**
- Added missing Hebrew keys for admin profile authenticator/password UI.
- Added missing Hebrew keys for patient home/profile portal text.

4. **Groups Manager UX Updated**
- Moved group-management controls from side-column layout into a top banner flow.
- Increased group description editing space.
- Session record section now presents status as a titled box above meeting content.
- Reordered member attendance row so `Notified` is adjacent to patient name.
- Missed-reason entry now uses a short prompt flow and appears only for missed status.
- Past/upcoming/next sections now appear as same-line tabs that replace each other.

5. **Calendar Simplification (Special -> Blocked)**
- Normalized backend block handling to treat `special` as `blocked`.
- Removed special-category controls from primary calendar UI.
- Updated block editor and save labels to blocked-only language.
- Simplified Zoom visual treatment to camera-icon presentation without separate color badge.

6. **Live Data Normalization Per Request**
- Created safety backup before cleanup:
  - `clinic.db.pre_user_cleanup_20260322_192614.bak`
- Applied cleanup in `clinic.db`:
  - converted special blocks to blocked,
  - removed all patient appointments,
  - left vacancy structures intact.
- Post-cleanup counts:
  - appointments: `0`
  - blocked_slots_special: `0`
  - blocked_slots_blocked: `111`
  - slots_override: `2`
  - vacancy_recurring: `6`

## Session 29

**Date:** March 21, 2026

**Objective:** Harden admin security, create a fresh full-data encrypted backup, and improve desktop/mobile usability.

**Release Summary:**

1. **Full Data Backup Confirmed**
- Created a fresh encrypted backup bundle: `secure_backups/clinic_20260321_100600.db.enc`.
- Backup bundle flow includes DB + local artifacts (`static/uploads`, `patients_logs`, and `app_log.txt`) for migration-safe restore.

2. **Admin Credentials + Security Upgrades**
- Default admin bootstrap/migration now targets username `lioraloni` with initial password `12345`.
- Added admin Google Authenticator flow using TOTP:
  - setup start,
  - QR/manual secret display,
  - verification,
  - optional disable.
- Login now supports 2-step verification for admin accounts with authenticator enabled.
- Added admin password-change endpoint requiring current password + valid authenticator code.
- Added `users` security fields in schema/migrations: `totp_secret`, `totp_enabled`, `force_password_change`.

3. **UI Improvements (Desktop + Mobile)**
- Expanded effective site width for desktop via shared app container sizing in layout.
- Improved mobile readability for patient records/file names.
- Added mobile read-mode behavior on patient detail screens that limits editing actions while preserving reading/navigation.

4. **Tests Updated And Verified**
- Updated app tests for new default admin credentials.
- Added security tests for TOTP second-step login.
- Test results:
  - `python test_security.py` passed (`5` tests)
  - `python test_app.py` passed (`50` tests)

## Session 28

## Session 31

**Date:** March 23, 2026

**Objective:** Implement 11 calendar and CRM improvements for enhanced booking and patient management functionality.

**Release Summary:**

1. **Patient Dropdown Organization**
  - Updated patient_options query to sort by patient_type then name.
  - Implemented Jinja2 optgroup grouping in calendar.html for organized dropdown display.
  - Patients grouped by status types (ongoing, candidate, archived) then clinic types.
  - Improves UX for selecting from large patient lists.

2. **Editable Booking Date and Time**
  - Added visible date input field (bookingDateInput) to booking panel.
  - Added visible time input field (bookingTimeInput) to booking panel.
  - Implemented JavaScript event listeners to sync visible fields with hidden form fields.
  - Updated setSelectedSlot() to synchronize both visible and hidden fields bidirectionally.
  - Allows admins to directly edit or adjust selected booking time without calendar re-selection.

3. **Recurring Event Deletion Fix**
  - Fixed api_calendar_appointment_delete route "upcoming" scope logic.
  - Updated to use recurring_occurrences_between() for proper series validation.
  - Now correctly truncates series to cutoff date vs deleting entire group.
  - Handles three scopes correctly: one (exclude), upcoming (truncate), all (delete).

4. **Meeting Type Options Update**
  - Changed meeting type options from [zoom, google-meet, in-person] to [online, in-person, phone].
  - Added conditional meeting link field visibility (only visible for "online" type).
  - Updated JavaScript to show/hide meeting link container based on selected type.

5. **Meeting Title → Meeting Remarks**
  - Renamed "Meeting Title" field to "Meeting Remarks" in calendar.html form.
  - Changed field name from meeting_title to meeting_remarks.
  - Set blank default placeholder (no pre-filled text).
  - Implemented backward compatibility fallback in api_calendar_book route.
  - Database still uses meeting_title column for existing data compatibility.

6. **Recurring Meeting Checkbox**
  - Added recurring checkbox (id: recurringCheckbox) to booking form.
  - Added conditional date picker (recurringDateWrap) that shows when recurring is enabled.
  - Implemented status-based defaults: ongoing=checked (auto-recurring), candidate/waiting=unchecked.
  - JavaScript event listener toggles date picker visibility on checkbox change.
  - Patient change handler updates checkbox state based on patient status.

7. **Backend Support for New Form Fields**
  - Updated api_calendar_book route to extract meeting_remarks from form.
  - Updated api_calendar_book to extract is_recurring checkbox value.
  - Updated api_calendar_book to extract recurrence_end_date from form input.
  - Implemented logic: form values override auto-detection based on patient status.
  - Default recurrence_end_date = anchor + 365 days if recurring enabled.

8. **CRM Filter Enhancement - Clinic Type**
  - Updated crm_dashboard route to accept clinic_type parameter.
  - Added validation for clinic_type: {all, private, residency, group}.
  - Stores clinic_type in session['crm_filters'] for persistence.
  - Updated template to pass clinic_type instead of patient_type.
  - Fixed all 4 summary strip URLs to use clinic_type parameter.
  - Allows filtering patients by clinic classification separately from status.

9. **"Other" Booking Type Option**
  - Added "other" option to bookingTypeSelect dropdown.
  - Added conditional input field (otherBookingTypeInput) for custom booking type entry.
  - JavaScript toggles input field visibility when "other" is selected.
  - Form submission validates custom booking type is not empty before submitting.
  - Custom type value submitted with form when booking_type="other".

10. **Group Page Dropdown UI Refactor**
   - Changed .group-side-accordion CSS from grid layout to flex column layout.
   - Updated to display: flex; flex-direction: column for full-width stacking.
   - Removed rounded corners (rounded-4 → rounded-0) for seamless accordion appearance.
   - Removed bottom margins (mb-3) for proper spacing in stacked layout.
   - Result: only one accordion section can expand at a time, spans full width.

11. **Dummy Patient Cleanup**
   - Soft-deleted dummy patients using is_deleted flag:
    - John (patient_id=18)
    - Dov Lev (patient_id=25)
    - Dirk Gently (patient_id=26)
   - Used soft-delete (is_deleted=1) to preserve referential integrity.
   - Existing queries filter out deleted patients via COALESCE(is_deleted, 0) = 0.

**Testing & Verification:**
- Python syntax validation: PASSED
- Flask app imports: PASSED
- Database schema verification: All required columns present
- Patient sorting query execution: PASSED (correct type+name ordering)
- Code review: All 11 features present and correctly implemented

**Files Modified:**
- app.py: Patient sorting query, api_calendar_book route, api_calendar_appointment_delete fix, crm_dashboard filter
- templates/calendar.html: Patient dropdown grouping, date/time inputs, meeting remarks, recurring checkbox, "other" type, meeting type options
- templates/crm.html: Clinic type filter dropdown and URL parameter updates
- templates/groups.html: Accordion CSS layout refactoring
- clinic.db: Soft-deletion of dummy patients

**Git Commit:**
- Hash: a6fd736
- Message: "Implement 11 calendar and CRM improvements"
- Status: Successfully pushed to origin/main

---
**Date:** March 17, 2026

**Objective:** Complete the latest patient-portal workflow pass for intake scheduling, patient-side meeting requests, and translation cleanup.

**Release Summary:**

1. **Intake And Diagnosee Booking Rules Updated**
- Kept `initial-intake` and `diagnosee` appointments non-recurring by default.
- Removed the forced deletion of existing scheduled meetings so additional one-time meetings can be booked when clinically needed.

2. **Patient Request Workflow Added**
- Added patient-side cancellation requests from the portal, including a required explanation.
- Added patient-side requests for another meeting / self-booking access from available slots.
- Both request types now create system-style chat messages for admin review and patient acknowledgment, and include audit log entries.

3. **Portal Translation And UX Cleanup**
- Localized the patient home page strings added in recent releases.
- Added the new request actions to the patient portal without breaking existing messaging, receipts, or shared-document sections.

**Validation:**

1. **Automated Tests**
- `python test_app.py` passed (`50` tests).
- `python test_security.py` passed (`3` tests).

2. **Targeted Smoke Check**
- Verified patient cancellation and booking-access requests return `200`, create chat messages, and write `patient-cancel-request` / `patient-booking-request` audit actions.

## Session 27

**Date:** March 16, 2026

**Objective:** Finalize the latest group-management release with a focused regression review and a concise release summary.

**Release Summary:**

1. **Group Lifecycle Controls Expanded**
- Added archive-vs-delete handling for groups.
- Added remove-vs-archive-vs-delete handling when removing a member from a group.

2. **Group Session Workspace Reworked**
- Reorganized the group detail page into collapsible management sections.
- Kept session records visible in presentation mode until the user explicitly presses edit.
- Expanded writing space for session summaries and member comments.
- Limited the default session list to the nearest upcoming and previous records, with show-all controls.

3. **Scheduling and Navigation Improved**
- Added recurring-series end selection by count or end date.
- Redirected newly created group sessions to the newest session record.
- Added direct calendar click-through from group sessions to the matching group-session record.

**Regression Review:**

1. **Automated Validation**
- Full suite: `python test_app.py` passed (`50` tests).
- Targeted group regression checks passed for:
  - group archive vs full delete,
  - member archive flow,
  - member full-delete flow,
  - calendar snapshot `detail_url` linking.

2. **Review Outcome**
- No regressions were found in the reviewed group-management and calendar handoff flows.
- The push on `main` reflects the reviewed state.

## Session 26

**Date:** March 16, 2026

**Objective:** Split group management into overview vs per-group sessions pages, and add collapsed-by-title behavior in booking panel sections.

**Changes Made:**

1. **Groups Overview vs Group Sessions Split**
- Added a dedicated overview template `groups_overview.html` for:
  - creating groups,
  - editing basic group metadata,
  - opening a specific group sessions workspace.
- Kept `/groups` focused on group list + metadata management.

2. **Single-Group Sessions Workspace**
- Reworked `groups.html` into a pure detail view for one group (`/groups/<id>`), including:
  - group info editing,
  - member management,
  - membership history date editing,
  - session scheduling and recurring setup,
  - session attendance/status/summary recording.

3. **Collapsible Session Regions**
- Converted group sessions display to accordion behavior so each session opens/collapses by clicking its title row.

4. **Booking Panel Collapsible Sections**
- Implemented title-triggered collapses in the Booking tab of `calendar.html`.
- Booking section card bodies now start hidden and expand/collapse by clicking the section title.

5. **Routing/Redirect Consistency for New Flow**
- Continued redirect hardening so group actions route back to per-group detail context where appropriate.

6. **Tests Updated and Verified**
- Updated group suggestion test to validate the new detail-page location for member suggestions.
- Verification:
  - `python test_app.py` passed (`46` tests),
  - `python test_security.py` passed (`3` tests).

## Session 25

**Date:** March 16, 2026

**Objective:** Refine group tab and group management so groups behave as ongoing treatment units with richer attendance controls and patient-card integration.

**Changes Made:**

1. **Group Membership Suggestions Restricted to Group Patients**
- Group member picker now suggests only patients where `patient_type='group'`.
- Backend now enforces this rule on add-member requests.

2. **Editable Group Join/Leave Dates**
- Added date editing for membership periods (`joined_date`, `left_date`) directly from:
  - group management history panel,
  - patient private card.
- Added synchronization logic so current active membership state remains consistent.

3. **Attendance: Missed + Notified Binary Flag**
- Added `notified_on_time` boolean on group attendance records.
- Group session recording now supports:
  - arrived/missed status,
  - missed reason,
  - notified-correctly checkbox,
  - per-patient attendance note.

4. **Patient Private Card Integration for Group Meetings**
- Added a dedicated **Group Participation** card in patient profile with:
  - private arrived counter,
  - attendance timeline per group meeting,
  - group-wide session summary visibility,
  - inline edit capability for attendance + summary from patient card.

5. **Missed Group Note De-duplication**
- Improved missed-group auto-note behavior to upsert by session marker instead of creating duplicates on repeated edits.

6. **Tests Added/Updated**
- Added/updated regression tests for:
  - group-only suggestion/enforcement,
  - membership date editing,
  - notified flag persistence,
  - patient-card attendance and summary editing.

## Session 24

**Date:** March 16, 2026

**Objective:** Expand group lifecycle management with historical membership tracking, recurring group meetings, attendance + missed-reason documentation, and individual missed-meeting documentation in treatment logs.

**Changes Made:**

1. **Group Membership History + Durations**
- Added persistent `group_member_history` tracking for join/leave cycles.
- Updated member add/remove logic to preserve historical periods while keeping current active membership.
- Added member-history UI in `groups` page showing joined date, left/active state, and days in group.

2. **Recurring Group Session Scheduling + Future-Series Updates**
- Added recurrence support when creating group sessions:
  - one-time,
  - weekly recurring,
  - interval in weeks,
  - count and/or end-date caps.
- Added `group_session_series` metadata and linked sessions via `series_id`.
- Enhanced group session update API to support:
  - single-session update,
  - apply-to-future updates for recurring series.

3. **Group Session Outcomes + Attendance Tracking**
- Added session outcome recording (`session_summary`, session status).
- Added attendance table `group_session_attendance` with per-member:
  - attendance status (pending/present/missed),
  - missed reason,
  - attendance note.
- Added session recording form in `groups` UI to capture what happened and who arrived/missed.

4. **Missed Meeting Documentation in Individual Treatment**
- Added treatment-log support for missed sessions with:
  - `is_missed_meeting`,
  - `missed_reason`.
- Updated create/edit note flows and patient detail UI to capture and display missed-session reasons.
- Group missed attendance now auto-creates an individual missed-meeting note for that patient.

5. **Schema + Migration Hardening**
- Updated `schema.sql` and `init_db()` migrations for new fields/tables/indexes:
  - `group_member_history`,
  - `group_session_series`,
  - `group_session_attendance`,
  - `group_sessions.series_id/occurrence_index/session_summary`,
  - `notes.is_missed_meeting/missed_reason`,
  - `appointments.missed_reason`.

6. **Automated Regression Coverage**
- Added tests for:
  - member history join/leave/rejoin periods,
  - recurring group session creation and future-series update,
  - attendance capture + missed reason + auto-created individual note,
  - individual missed-treatment note reason persistence.

## Session 23

**Date:** March 15, 2026

**Objective:** Fix intake tab placement so Summary and Intake sections render in the correct tabs for patient profiles.

**Root Cause:**
- The JavaScript tab relocation helper moves the element with id `intakeEvaluationFormBlock` into the Intake tab host.
- That id was incorrectly attached to the **Background** card, causing Background to appear under Intake.

**Changes Made:**

1. **Template ID Correction**
- In `templates/patient_detail.html`:
  - Removed `id="intakeEvaluationFormBlock"` from the Background card in Summary.
  - Assigned `id="intakeEvaluationFormBlock"` to the Intake Evaluation Form card (the one with DOCX export).

2. **Behavior After Fix**
- Summary tab keeps the Background section.
- Intake tab receives the Intake Evaluation Form block, including DOCX export button.

**Verification Performed:**
- Full app tests (`python test_app.py`).
- Security tests (`python test_security.py`).

**Result:**
- Tab content placement corrected with no functional regressions observed in automated tests.

## Session 22

**Date:** March 15, 2026

**Objective:** Apply deeper database performance hardening with zero feature changes.

**Changes Made:**

1. **Database Indexing Hardening**
- Added a conservative, idempotent index set in `init_db()` (`app.py`) for high-frequency query patterns.
- Added matching index declarations in `schema.sql` so new database setups are optimized immediately.

2. **Index Coverage Added**
- Patients filters: status/type with soft-delete flag.
- Users by `patient_id` lookup.
- Appointments by patient/date/time and status/date lookup patterns.
- Notes, receipts, files by `patient_id` + `created_at` sort/filter paths.
- Messages by recipient/read/timestamp and sender-recipient conversations.
- Calendar availability/blocks tables by date/time/status.
- Group membership/session lookup paths.
- Notifications unread sorting and goals by patient/status.

**Verification Performed:**
- Syntax compilation for app module.
- Full application tests (`python test_app.py`).
- Security tests (`python test_security.py`).

**Result:**
- No functional behavior changes introduced.
- Automated tests remained green after index hardening.

## Session 21

**Date:** March 15, 2026

**Objective:** Remove redundant script, improve runtime efficiency in CRM counts, and strengthen operational diagnostics while preserving behavior.

**Changes Made:**

1. **Removed Redundant Script**
- Deleted unused frontend script file `static/script.js`.
- Verified no template references were using this file.

2. **Import Cleanup in App Module**
- Removed duplicate top-level `jsonify` import from `app.py`.
- Removed redundant function-local imports of `json` and `Response` in export/import routes, using existing module-level imports instead.

3. **CRM Dashboard Query Optimization**
- Replaced four separate patient `COUNT(*)` queries with a single aggregated SQL query in `/crm` route.
- Preserved count semantics for:
  - all active patients,
  - ongoing,
  - candidate/waiting,
  - archived.

4. **Backup Robustness and Debug Visibility**
- Updated routine backup guard to log backup failures via Flask logger while continuing request processing.
- Behavior remains non-blocking for end users if backup execution fails.

**Verification Performed:**
- Syntax compilation check for `app.py`.
- Full app tests via `python test_app.py`.
- Security tests via `python test_security.py`.

**Result:**
- No behavioral regressions observed in automated verification.

## Session 20

**Date:** March 15, 2026

**Objective:** Continue localization pass 3 by reducing untranslated UI text in high-impact pages.

**Changes Made:**

1. **Admin Profile Localization**
- Converted static labels/buttons/messages in `templates/admin_profile.html` to translation helper calls.

2. **Legacy Open Booking Page Localization**
- Localized static text in `templates/open_booking.html`.
- Refactored JavaScript message localization to use `data-*` attributes, avoiding template syntax in JS and fixing diagnostics.

3. **Hebrew Dictionary Expansion**
- Added new keys in `translations/he.json` for admin profile and legacy open-booking text.

4. **Translation Audit Improvement**
- Regenerated `translation_audit.txt` and reduced remaining unmatched entries from `201` to `181`.

**Test Results:**
- `python test_app.py` passed (`36` tests).

## Session 19

**Date:** March 15, 2026

**Objective:** Add public available-slot self-booking by shareable link/email, enforce booking field requirements, and notify admin as pending patient.

**Changes Made:**

1. **Public Self-Booking Link Generation**
  - Added admin endpoint to create secure public booking links.
  - Added calendar admin UI controls to:
    - generate link,
    - copy link,
    - open prefilled email compose (`mailto`) for sharing.

2. **Public Available-Slots Booking Page**
  - Added new page: `templates/open_booking_calendar.html`.
  - Displays only available slots and allows public self-booking.

3. **Public Booking Validation Rules**
  - Enforced on backend:
    - name is required,
    - date of birth optional,
    - phone or email (at least one) required,
    - selected slot must still be available.

4. **Pending Patient + Notification Flow**
  - On successful public booking:
    - creates a new patient with `waiting` status,
    - creates one-time appointment,
    - updates one-time vacancy status when relevant,
    - inserts admin notification for follow-up.

5. **Data Model Additions**
  - Added `public_booking_links` table migration in `init_db`.

6. **Localization Support**
  - Added translation wrappers and Hebrew dictionary entries for new public-link feature text.

7. **Tests Added**
  - Added regression tests for:
    - missing phone/email rejection,
    - successful public booking creating waiting patient, appointment, and notification.

**Test Results:**
- `python test_app.py` passed (`36` tests).

## Session 18

**Date:** March 15, 2026

**Objective:** Run a second Hebrew localization sweep focused on the calendar page and reduce remaining English UI strings.

**Changes Made:**

1. **Calendar Template Localization Sweep**
  - Localized additional static labels/buttons/placeholders in `templates/calendar.html`.
  - Added translation wrappers for booking management section labels and headers.

2. **Dynamic Calendar UI Localization (JavaScript)**
  - Added a centralized `I18N` dictionary object in calendar script.
  - Replaced key dynamic modal/toast/editor strings with translatable values.
  - Fixed string interpolation and ensured runtime messages respect active language.

3. **Hebrew Dictionary Expansion**
  - Added a broad set of calendar-specific keys to `translations/he.json`.

4. **Translation Audit Refresh**
  - Regenerated `translation_audit.txt` after the sweep.
  - Remaining unmatched English entries reduced from 241 to 201.

**Test Results:**
- `python test_app.py` passed (`34` tests).

## Session 17

**Date:** March 15, 2026

**Objective:** Address intake tab layout issues, quick-book recurrence control, and make Hebrew translation editing easier through a dictionary file.

**Changes Made:**

1. **Initial Intake Add-Patient Cleanup**
  - Removed the two free-text intake fields from the Add Patient page.
  - Intake setup now starts cleanly from the dedicated intake evaluation workflow.

2. **Quick Book Recurrence Switch (Patient Quick Actions)**
  - Added recurrence mode selector to quick-book form:
    - Auto (by patient type)
    - One-time meeting
    - Recurring weekly meeting
  - Backend now respects this selector and validates constraints.
  - Recurring mode is rejected for initial-intake patients with a clear validation message.

3. **Intake Tab Layout Fix**
  - Restored summary information cards to Summary tab.
  - Moved the actual Intake Evaluation form card to the Intake tab using the correct DOM block.

4. **Hebrew Translation Dictionary File**
  - Added editable dictionary file: `translations/he.json`.
  - Added override loader in `app.py` so dictionary edits apply without code changes.
  - Localized additional hardcoded form/button text in add-patient and quick-actions sections.

5. **Documentation**
  - Updated README with Hebrew dictionary usage notes.

**Test Results:**
- `python test_app.py` passed (`34` tests).

## Session 16

**Date:** March 12, 2026

**Objective:** Enhance UI/UX with three focused improvements: vacant slot visibility in calendar, dedicated intake form tab space, and quick booking action.

**Changes Made:**

1. **Vacant Slots Now Visible in Calendar**
   - Modified `build_week_calendar_snapshot()` in app.py to render available slots as distinct calendar events
   - Vacant slots appear with green color (#10b981) labeled as "Vacant (duration)min"
   - Admin-only feature to maintain clean UI for patient calendars
   - Added "Vacant Slot" badge to calendar legend for clarity

2. **Intake Form Dedicated Tab**
   - The Intake Evaluation Form already had proper dedicated tab support via JavaScript DOM movement
   - Form is rendered in its own tab (#intake) with full card styling and spacing
   - Export DOCX button remains accessible within the tab
   - Sub-tabs within form (Prelim, Background, Administrative, Medical, Mental Status, Treatment Plan) remain functional

3. **Quick Action: Book Appointment**
   - Added new quick action button to patient detail page Quick Actions panel
   - Button navigates directly to /weekly_calendar for easy appointment booking
   - Styled with info color (#0d6efd) to distinguish from intake form action
   - Appears for all patient types after Edit and Export History buttons

**Technical Details:**

- **app.py (lines 1804-1816)**: Added vacant slot event rendering for admins using #10b981 color
- **calendar.html**: Added "Vacant Slot" badge to legend for event type visibility
- **patient_detail.html**: Appended Book Appointment link after intake tab control

**Test Results:**
- Application Tests: ✓ 16/16 passed
- Security Tests: ✓ 3/3 passed
- Syntax Validation: ✓ Passed

**Dependencies:**
- No new dependencies introduced
- Uses existing calendar event infrastructure
- Leverages existing route structure (weekly_calendar)

**User Impact:**
- Admins can now see all bookable slots at a glance in calendar view
- Patients have immediate access to book appointments from patient profile
- More screen real estate for intake form completion on dedicated tab

**Next Steps (Future):**
- Real-time vacancy counter on quick action button
- Batch slot availability import from external scheduling systems
- Intake form progress indicator (e.g., "4/6 sections completed")

## Session 15 — March 12, 2026 (Phase 1: Group Meetings History and Management)

### Overview
Started implementation of group meeting management by introducing dedicated group data models, admin workflows, and calendar integration.

### 1. New Group Data Model
- Added DB support for:
  - `groups` (name, type, description, active flag)
  - `group_members` (group-to-patient assignment with join/leave tracking)
  - `group_sessions` (scheduled sessions with date/time/duration/link)
- Added migration-safe creation in `init_db` and schema coverage in `schema.sql`.

### 2. Admin Group Management Routes
- Added admin routes:
  - `GET/POST /groups` to view and create groups
  - `POST /groups/<group_id>/members` to add a patient to a group
  - `POST /groups/<group_id>/members/<patient_id>/remove` to remove a member
  - `POST /groups/<group_id>/sessions` to schedule a group session
  - `POST /groups/sessions/<session_id>/delete` to delete a session

### 3. Groups Admin UI
- Added new template: `templates/groups.html`.
- Includes:
  - Group creation form
  - Per-group member management
  - Per-group session scheduling
  - Upcoming session list with deletion
- Added a `Groups` admin nav action in `layout.html`.

### 4. Calendar Integration
- Group sessions now appear in weekly calendar snapshot events with a dedicated color.
- Group sessions are also considered occupied time, preventing slot collisions.
- Updated calendar legend to include Group Session indicator.

### Verification
- `python -m py_compile app.py test_app.py` passed.
- `python test_app.py` passed (`16` tests).
- `python test_security.py` passed (`3` tests).

---

## Session 14 — March 12, 2026 (Vacancy-Gated Booking, Sticky CRM Filters, Messaging Ribbon, Intake Tab Controls)

### Overview
Implemented the requested behavior fixes for booking permissions, CRM filter persistence, admin chat ribbon visibility, and intake tab access controls.

### 1. Booking Restricted to Admin-Enabled Vacancies
- Calendar booking availability is now sourced from explicit admin vacancy records (`slots_override` with `status='available'`).
- Added admin endpoint: `/api/calendar/vacancy` to enable a date/time window as bookable.
- Added UI in calendar block management tab: **Enable Vacant Slot** (date, start time, end time).
- Booking now succeeds only when the selected slot exists in enabled vacancies and remains non-overlapping with appointments/blocks.

### 2. CRM Filters Persist Across Page Returns
- CRM filter state (`status`, `patient_type`, `q`, `sort`) is now persisted in session.
- Returning to `/crm` without query parameters restores the last active filter set.
- Status summary cards now preserve active search/type/sort filters when switching status buckets.

### 3. Messages Ribbon Includes Patients Without Message History
- Admin conversation list now uses patients as the base dataset and includes rows even with no prior messages.
- Added support for listing patients that do not yet have a portal login (displayed but non-selectable for sending).
- API filtering by search/type/status now applies server-side for conversation list retrieval.

### 4. Intake Form Placement and Enablement
- Intake tab visibility now supports either:
  - `patient_type='initial-intake'`, or
  - explicit `has_intake_tab=1`.
- Added migration/schema support for `has_intake_tab`.
- Added quick action for non-intake patients: **Enable Intake Tab**.
- Intake form state now posts with `active_tab='intake'` to remain on the intake tab after save.

### 5. Test Updates and Verification
- Updated booking tests to create explicit vacancies before booking actions.
- Verification:
  - `python test_app.py` passed (`16` tests)
  - `python test_security.py` passed (`3` tests)

---

## Session 13 — March 12, 2026 (Refinement Pass: Status Colors, Collapsed Filters, Admin Name, Strict Calendar Windows)

### Overview
Applied a focused refinement pass to align UI behavior with requested semantics, tighten scheduling availability windows, and fix admin identity rendering.

### 1. Status-Driven Card Semantics (Main + CRM)
- Removed visible status badges (`Ongoing`, `Candidate`, etc.) from card headers.
- Switched card backgrounds to **status-based color coding**:
  - ongoing = green
  - candidate/intake = yellow
  - waiting = blue
  - archived/other = gray
- `initial-intake` now behaves like a **status-level candidate visual state** (instead of a separate type badge in card header).

### 2. Type Badge Placement Simplification
- Kept only a compact type badge at the end of the ID row.
- Residency remains explicitly tagged as `Residency`.
- All non-residency patients are shown as `Private` for display consistency.

### 3. CRM Filter UX Compact Mode
- Moved CRM search/type/sort controls into a **collapsed panel**.
- Added a funnel icon toggle button to open/close filters.
- Removed `initial-intake` from type filter options to keep intake behavior status-centric.

### 4. Admin Display Name in Navbar
- Updated authenticated user model loading so `display_name` is available on `current_user`.
- Navbar now renders `display_name` with username fallback.
- Profile updates are now immediately reflected in the top-right identity button.

### 5. Calendar Availability Restricted to Explicit Windows
- Replaced broad workday slot generation with explicit allowed windows:
  - Sunday: 14:00–15:00
  - Monday: 09:00–10:00, 12:30–13:30
  - Thursday: 10:00–15:00, 19:00–20:00
  - Tuesday/Wednesday: no availability
- Availability slots continue to honor overlap checks against existing appointments and blocks.

### 6. Test Alignment and Verification
- Updated booking-related tests to select valid allowed slots dynamically under the new window rules.
- `python test_app.py` passed (`16` tests).

---

## Session 12 — March 12, 2026 (Intake Workflow, CRM Filters, Messaging, Admin Profile, Backup Security)

### Overview
Implemented a broad UX and workflow update across intake handling, CRM filtering/sorting, chat usability, top navigation cleanup, admin identity management, and encrypted backup reliability.

### 1. Intake Workflow Integration
- Added a dedicated **Intake Evaluation** main tab in patient profile for `initial-intake` patients.
- Intake form is now presented as its own top-level tab alongside Summary, Treatment Log, Billing, and Messages.
- For intake patients, default tab now opens Intake directly.
- Quick Actions replaced Treatment Log shortcut with an Intake Form shortcut for intake patients.

### 2. CRM and Main Card Experience
- Added CRM controls for:
  - free-text search (`name/email/phone`)
  - patient type filter (`private`, `residency`, `initial-intake`)
  - sorting (status priority, name A-Z/Z-A, newest/oldest)
- Updated patient cards to use full background coloring by patient type.
- Added clear patient-type tags (Private/Residency and Intake badge).
- Removed redundant View Profile buttons from card grids and kept full-card click navigation.
- Intake cards now navigate directly to the intake tab.

### 3. Top Navigation Cleanup
- Removed redundant top blue-bar links for Ongoing / Candidates & Waiting / Archived.
- Kept primary action buttons (Add Patient, Resources, Calendar).

### 4. Admin Identity and Profile Management
- Added admin profile page (`/admin/profile`) with editable fields:
  - display name
  - email
  - phone
  - id number
  - date of birth
- Navbar admin identity is now a button with a **crown icon** linking to profile settings.
- Added user schema support and migration coverage for new profile fields.

### 5. Messaging Improvements (Admin)
- Enhanced message drawer to support contacting patients even with no prior thread.
- Added recipient search and filtering in the chat drawer by:
  - patient name/user text
  - patient type
  - patient status
- Backend API now returns patient type metadata and supports query filtering.

### 6. Encrypted Backup and Data Safety
- Added encrypted backup support with `cryptography` (Fernet):
  - encrypted `.db.enc` backup artifacts
  - periodic routine backup guard
  - manual backup trigger endpoint (`/admin/backup_now`)
- Added `cryptography` to `requirements.txt`.

### Verification
- `python test_app.py` passed (`16` tests).

---

## Session 11 — March 11, 2026 (Special Booking Flow, CRM Views, Hebrew Coverage)

### Overview
Implemented the latest UX and workflow updates across calendar and CRM, including moving Special scheduling into Booking Panel, adding card/list presentation mode in CRM, and extending Hebrew translation coverage for updated UI labels.

### 1. Special Moved from Block Panel to Booking Panel
- Added `Booking Type` in Booking Panel with:
  - `Appointment` (default)
  - `Special` (purple-highlighted selection)
- When `Special` is selected:
  - `Special Pattern` field appears (`One-time` / `Weekly Recurring`)
  - `Repeat Until` field appears for weekly recurring mode
  - `Special Title` field appears
- Kept block creation tab for **blocked intervals only**.

### 2. Special Availability Behavior
- `api_calendar_book` now supports `booking_type=special`.
- Special slots are saved to `blocked_slots` with `block_type='special'`.
- Recurring special slots are expanded weekly until the selected end date.
- Overlap checks prevent inserting special blocks over existing appointments/blocks.
- Patients still do **not** see blocked/special events, and those slots are excluded from available slots.

### 3. Calendar Bug Fixes and UI Polish
- Fixed stale `bookingDuration` reference in `dateClick` callback (now defaults to 60-minute selection when clicking a slot cell).
- Added admin-only display for blocked/special filter chips.
- Added broader `t(...)` wrappers in calendar headers, labels, legends, and button text for Hebrew mode consistency.

### 4. CRM Main Page Updates
- Removed top action buttons for:
  - Weekly Calendar
  - Add Patient
- Added view mode toggle in CRM patient section:
  - `Cards`
  - `List`
- Implemented responsive list-mode styling so mobile layout remains intact.
- Added translation wrappers for CRM title/summary and view-mode controls.

### 5. Hebrew Translation Coverage
- Extended `HEBREW_TRANSLATIONS` with new strings used by:
  - Calendar new controls (`Booking Type`, `Special Pattern`, `Repeat Until`, etc.)
  - CRM list/card mode labels and headers

### Verification
- `python3 test_app.py` passed (`14` tests)
- `python3 test_security.py` passed (`3` tests)

---

## Session 10 — March 11, 2026 (Booking UX, Calendar Fixes, Patient Type, Meeting Links)

### Overview
Wide-scope improvement pass covering 6 requested features + bug fixes across the calendar, patient management, and booking flows.

### 1. Calendar Layout Fix on Tab Switch
- **Problem:** The FullCalendar grid rendered incorrectly (collapsed columns, overlapping text) when switching away from the Schedule tab and returning.
- **Fix:** Added `shown.bs.tab` listener on `#schedule-tab` that calls `calendar.updateSize()` to force FullCalendar to recalculate its dimensions after the tab becomes visible again.

### 2. Start/End Time Instead of Duration
- **Booking Panel (`#booking-pane`):** Replaced the "Duration (minutes)" dropdown with an "End Time" time input. Duration is now computed automatically as `end_time - start_time` in both the UI and backend.
- **Add Block / Special (`#blocks-pane`):** Replaced the "Duration (minutes)" number input with a "Start Time" + "End Time" pair (15-minute stepping).
- **Backend (`api_calendar_book`, `api_calendar_block`):** Both endpoints now accept `end_time` instead of `duration_minutes`. Duration is computed server-side from `start - end` with a 60-minute safe default.
- **`setSelectedSlot()` updated** to display `date HH:MM → HH:MM` instead of `(N min)`.

### 3. Patient Calendar: Blocked Slots Hidden from Patients
- **Problem:** Blocked slots (and special occasions) were visible to patients as "Unavailable" entries in the calendar.
- **Fix (`build_week_calendar_snapshot`):** Blocked/special entries are still added to the `occupied` set (so available slots remain accurate), but the calendar `events` list only includes them when the viewer is an admin. Patients never see blocked time entries.
- **Legend updated:** Blocked/Special badges in the Schedule tab legend are now wrapped in `{% if current_user.role == 'admin' %}`.

### 4. Patient Type Field (Private / Residency)
- **DB migration:** `ALTER TABLE patients ADD COLUMN patient_type TEXT DEFAULT 'private'`
- **Add Patient form (`add_patient.html`):** Added radio buttons for "Private" vs "Residency" below the phone field.
- **Edit Patient form (`edit_patient.html`):** Same radio buttons, pre-selects current value.
- **Patient Detail (`patient_detail.html`):** Shows a colour-coded badge (purple for Residency, muted for Private) next to the status badge.
- **CRM Dashboard (`crm.html`):** Residency patients show a small "Residency" badge next to their ID.
- **`add_patient` / `edit_patient` routes in `app.py`:** Accept and persist `patient_type` with validation against `('private', 'residency')`.

### 5. Google Meet / Zoom Meeting Link Integration
- **New meeting type options:** Added `zoom` and `google-meet` to the Meeting Type dropdown in the Booking Panel (previously only `in-person` and `online`).
- **Helper buttons:** Two buttons added next to the Meeting Link URL field:
  - **Meet** button: opens `https://meet.google.com/new` in a new tab with `noopener,noreferrer` (no API key required — admin copies the generated link manually).
  - **Zoom** button: opens `https://zoom.us/start/videomeeting` in a new tab.
  - Clicking either button also auto-selects the corresponding meeting type in the dropdown.
- **`meeting_platform` column:** Added to the `appointments` table to store the platform independently of `meeting_type`. Both are sent from the frontend and persisted.

### 6. Zoom / Google Meet Icon in Calendar Events
- **`eventContent` callback** added to the FullCalendar configuration.
- Meetings with `meeting_platform = 'zoom'` or `meeting_type = 'zoom'` show a filled camera icon (`bi-camera-video-fill`).
- Meetings with `meeting_platform = 'google-meet'` or `meeting_type = 'google-meet'` show an outline camera icon (`bi-camera-video`).
- Legend updated with a "Zoom" camera-video badge for player reference.

### Bug Fixes
- `api_calendar_block` was accepting a free-form `duration_minutes` integer input that could be negative or zero — replaced by computed end−start with a 60-minute fallback.
- Calendar `booking_date` local variable was also used for form parsing, causing potential shadowing with `appointment_date` in the INSERT — renamed/traced to confirm no conflict.
- `appt.keys()` check for `meeting_platform` column ensures graceful fallback on legacy DB rows that predate the migration.

### Tests
- All 14 `test_app.py` tests pass.
- All 3 `test_security.py` tests pass.

---

## Session 9 - March 11, 2026 (Stability, Debugging, and Verification)

### Overview
Completed a full debug and verification pass on current calendar and test updates, then aligned security tests and dependency declarations with the current app behavior.

### Fixes Applied
- Added deduping guard for weekly calendar event emission to avoid duplicate recurring render collisions.
- Improved weekly calendar UI workflow (tabs, modal confirmations, grouped available slots, ongoing list, current-week auto-roll behavior).
- Added `.venv/` to `.gitignore` to avoid accidental environment commits.
- Added missing dependency `pyotp` to `requirements.txt`.
- Rewrote `test_security.py` from outdated OTP/`secret_token` assumptions to current login security behavior.

### Verification
- `WTF_CSRF_ENABLED=False python3 test_app.py` passed (`14` tests).
- `python3 test_security.py` passed (`3` tests).
- `python3 test_db.py` completed successfully (schema verification output).

---

## Session 8 — March 10, 2026 (Calendar UX Polish)

### Overview
Added a usability polish pass on top of the weekly snapshot calendar to improve planning speed and clarity.

### UX Enhancements
- Added visual legend for event meaning (ongoing, candidate/waiting, archived, blocked, special).
- Added interactive filter chips to toggle visible event groups in the calendar view.
- Added drag-to-book support:
  - selecting a time range now sets date, time, and duration in booking panel.
  - duration selector added to booking panel.
- Added half-hour slot granularity for availability generation (08:00-20:00, Sun-Thu).

### Backend Adjustments
- Calendar event metadata now includes `patient_status` for precise frontend filtering.
- Time parsing now accepts `HH:MM` and `HH:MM:SS`.
- Booking normalizes appointment time values before insert.

### Files Updated
- `templates/calendar.html`
- `app.py`
- `CHANGES.md`

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`14` tests).

---

## Session 7 — March 10, 2026 (Workweek Snapshot Calendar + Self-Booking)

### Overview
Implemented a new weekly scheduling system focused on operational snapshot planning (not meeting journaling), with workweek visibility, weekend special handling, blocked intervals, private admin-only labels, and controlled patient self-booking.

### Features Implemented

#### 1. Treatment-log template now specifies checklist options
- Updated `static/treatment_log_template.json` to include `behavior_checklist_allowed_values` in the template entries.
- This gives explicit allowed values when editing/importing previous sessions.

#### 2. Removed extra Clinic CRM text button in ribbon
- Removed the additional `Clinic CRM` nav text link.
- Main brand/title remains the single entry point to CRM.

#### 3. New weekly calendar system
- Added route: `/calendar` and new template: `templates/calendar.html`.
- Added API: `/api/calendar/snapshot` returning a week snapshot payload.
- Main calendar view configuration:
  - Sunday-Thursday only
  - 08:00-20:00
  - Weekly time-grid snapshot

#### 4. Weekend special occasions side columns
- Calendar page now renders dedicated Friday and Saturday side panels.
- Weekend items are sourced from schedule overrides and support time + duration.

#### 5. Recurring vs one-time behavior
- Recurring appointments are expanded into weekly occurrences using recurrence rules.
- One-time intake/diagnostic meetings remain one-time and do not replicate.
- Added follow-up indicators for candidate/waiting patients with past one-time meetings and no future booking.

#### 6. Blocked intervals and private admin-only labels
- Extended `blocked_slots` model with:
  - `duration_minutes`
  - `title`
  - `is_private`
  - `block_type` (`blocked` or `special`)
  - `created_by`
- Patients see private entries as `Unavailable` while admins see full titles (e.g., supervision/seminar/group).

#### 7. Self-booking and deletion for users (controlled by admin)
- Added API `POST /api/calendar/book`:
  - Admin can book for any selected patient.
  - Patient can self-book only when `can_self_schedule = 1`.
- Added API `POST /api/calendar/appointment/<id>/delete`:
  - Admin can delete any appointment.
  - Patient can delete own appointments when self-management is enabled.

#### 8. Admin override management
- Added API `POST /api/calendar/block` for adding blocked/special intervals.
- Added API `POST /api/calendar/block/<id>/delete` for removing overrides.

### Additional UX wiring
- Added calendar nav access for both admin and patient in `templates/layout.html`.
- Added quick links from `templates/crm.html` and `templates/patient_home.html`.

### Files Updated
- `app.py`
- `schema.sql`
- `templates/calendar.html` (new)
- `templates/layout.html`
- `templates/crm.html`
- `templates/patient_home.html`
- `static/treatment_log_template.json`
- `test_app.py`
- `CHANGES.md`

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`14` tests).

---

## Session 6 — March 10, 2026 (CRM Navigation + Meeting History UX + Multi-Patient Messaging)

### Overview
Implemented requested admin UX updates across the main ribbon, treatment log structure, and messaging workflows. Added a dedicated CRM management dashboard and upgraded treatment log history into a nested, collapsible meeting view.

### Features Implemented

#### 1. Previous meetings now shown as titled, collapsible entries
- In the patient Treatment Log tab, each historical entry now renders as:
  - `Meeting #<number> - <date>`
- Clicking the meeting title expands meeting content.
- Inside each expanded meeting, a nested `Behavior & Appearance` toggle reveals:
  - appearance
  - mood summary
  - behavior notes
  - behavior checklist tags

#### 2. Treatment log split into two sections
- Treatment Log tab now has two clear sections:
  - `Last Meeting Record` (latest session snapshot)
  - `Treatment Log` (import + new entry form + full history)

#### 3. Public Resources removed from admin ribbon
- Main ribbon now hides `Public Resources` for admin users.
- Public resources link remains available for non-admin users.

#### 4. All-patients moved under Clinic CRM management tool
- Added new admin route: `/crm`.
- Added dedicated template: `templates/crm.html`.
- Admin homepage now redirects to CRM dashboard.
- `/patients` remains as a compatibility route and now redirects to `/crm` with status.
- CRM dashboard includes:
  - patient list by selected status
  - management cards (All/Ongoing/Candidates+Waiting/Archived)
  - management actions (`Add Patient`, `Manage Resources`)
  - **Download button for treatment log template** (`static/treatment_log_template.json`)

#### 5. Main ribbon messages upgraded to navigate by patient conversation
- Admin offcanvas messages now includes a patient conversation selector.
- Admin can navigate between patient conversations instead of seeing a single mixed stream.
- Backend `/api/messages` now returns admin conversation list + active thread.
- Backend `/api/messages/send` now requires `recipient_id` for admin messages.
- Existing patient message behavior remains unchanged.

### Backend/Code Changes
- Added helper `fetch_patients_by_status` in `app.py`.
- Added route `crm_dashboard` in `app.py`.
- Updated `index` route admin redirect to `crm_dashboard`.
- Added `latest_note` context in `patient_detail` route for last-meeting section.
- Enhanced `api_get_messages` and `api_send_message` for per-patient admin messaging.

### Files Updated
- `app.py`
- `templates/layout.html`
- `templates/patient_detail.html`
- `templates/crm.html` (new)
- `CHANGES.md`

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`12` tests).
- `python test_security.py` failed due missing local dependency: `pyotp` (`ModuleNotFoundError`).

---

## Session 5 — March 9, 2026 (Appearance/Behavior Questionnaire + JSON Template)

### Overview
Added structured appearance and behavior capture to the treatment log with auto-fill from the previous session. Also provided JSON template/example files and validated import against the live workflow.

### Features Implemented

#### 1. Appearance/Behavior questionnaire in Treatment Log
- Added a structured section to treatment log create/edit forms:
  - **Tick-box checklist** (`behavior_flags`)
  - **Short answer**: appearance overview (`patient_appearance`)
  - **Short answer**: mood summary (`mood_summary`)
  - **Short answer**: behavior notes (`behavior_notes`)

#### 2. Auto-fill from previous session
- On patient detail load, the latest note is read.
- Questionnaire values are pre-filled automatically into the next treatment log entry form.
- This supports continuity from one session to the next.

#### 3. Storage + migration support
- Added note-level fields via migrations and base schema updates:
  - `behavior_checklist`
  - `mood_summary`
  - `behavior_notes`
- Existing note fields (`note_date`, `patient_appearance`, `updated_at`) continue to be used.

#### 4. JSON template and example files
- Added reusable template at:
  - `static/treatment_log_template.json`
- Added concrete sample at:
  - `static/treatment_log_example.json`

#### 5. JSON import enhancements
- Import now accepts and maps questionnaire fields from JSON records:
  - `behavior_checklist` (array or string)
  - `mood_summary`
  - `behavior_notes`
  - `patient_appearance`
- Sorting behavior remains by date and meeting number.

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`12` tests).
- End-to-end live import check performed using `static/treatment_log_example.json`; records loaded with meeting/date/order and questionnaire fields.

### Files Updated
- `app.py`
- `schema.sql`
- `templates/patient_detail.html`
- `test_app.py`
- `static/treatment_log_template.json` (new)
- `static/treatment_log_example.json` (new)
- `CHANGES.md`

---

## Session 4 — March 9, 2026 (Treatment Log Workflow + Patient Detail UX)

### Overview
Implemented a focused upgrade of the patient detail workflow with emphasis on treatment-log operations, import/edit lifecycle, and keeping users on the same tab after form actions.

### What Changed

#### 1. Summary background box behavior
- Reworked the background section in patient summary to a closed preview box by default.
- Added an explicit Edit button that opens a collapsible editor.
- Save still updates patient info, but now keeps the user on the Summary tab.

#### 2. Appointments tab hidden for now
- Removed the Appointments tab button from patient detail navigation.
- Removed quick-action shortcut to appointments.
- Backend appointment endpoints remain intact for later re-enable.

#### 3. Clinical Notes renamed and form reshaped
- Renamed the visible tab label to Treatment Log.
- Changed treatment log entry form to use three core fields:
  - Meeting number
  - Date
  - Content

#### 4. Appearance/behavior placeholder
- Added a placeholder input for patient appearance/behavior in treatment log create/edit UI.
- Placeholder is visible but disabled to prepare for future activation.

#### 5. JSON treatment-log import flow
- Strengthened `/patient/<id>/import` JSON import handling for treatment logs.
- Supports flat list records using meeting/date/content fields.
- Imports are sorted by date and meeting number before insert.
- Imported notes now populate note date and meeting number consistently.

#### 6. Treatment log is editable post-creation
- Enabled per-note edit forms directly in the treatment log list.
- Edit supports updating meeting number, date, and content.

#### 7. Track when a treatment log entry was edited
- Added/used `updated_at` note field.
- Edit action updates `updated_at = CURRENT_TIMESTAMP`.
- UI now displays edited timestamp (or “Not edited yet”).

#### 8. Billing future upload placeholder
- Added disabled placeholder input for future external receipt upload support in billing form.

#### 9. Messaging behavior preserved
- Messaging flow was kept unchanged functionally.
- Redirect now keeps user on Messages tab after sending from patient detail.

#### 10. Keep same tab/page after actions
- Added tab-preserving redirect pattern for patient detail actions.
- Added tab state sync in UI (`tab` query param + hidden `active_tab` form input).
- Actions now return to the same working tab instead of always jumping to Summary.

### Backend/Migration Notes
- Added note migrations via `init_db()` for:
  - `note_date`
  - `patient_appearance`
  - `key_topics` (compatibility)
  - `updated_at`
- Note loading order now prefers `note_date`, then session number, then creation time.

### Files Updated
- `app.py`
- `templates/patient_detail.html`
- `test_app.py`
- `CHANGES.md`

### Verification
- `python -m py_compile app.py` passed.
- `python test_app.py` passed (`10` tests).

---

## Session 3 — Feature Branch Analysis & Integration

### Overview
Analyzed all 8 remote feature branches, identified valuable code, and selectively merged/extracted improvements while discarding conflicting or low-quality changes.

### Branch Decisions
| Branch | Decision | Reason |
|--------|----------|--------|
| `feature-crm-refactoring` | ✅ Merged | Port detection, `can_self_schedule`, notifications system, goals table, DOCX improvements |
| `enhance-clinic-crm` | ✅ Extracted | Goals CRUD, edit_note, Revenue dashboard, unread message context processor |
| `feature-calendar-doc-integration` | ❌ Discarded | Conflicting `/api/slots` schema |
| `feature-clinic-crm-updates` | ❌ Discarded | Test file only, no app code |
| `jules-clinic-app` | ❌ Discarded | 125-line skeleton (incomplete rewrite) |

### New Features Added

#### From `feature-crm-refactoring` (merged)
- **`can_self_schedule` flag** on patients — controls self-scheduling UI visibility; dashboard always shows calendar, shows info alert when self-scheduling is disabled
- **Notifications system** — `notifications` table populated when patients self-schedule/reschedule; admin gets toast alerts every 10s via `/api/notifications`
- **`goals` table** in schema + migrations
- **`is_port_in_use()` startup check** — warns if port 5000 is already occupied
- **`import socket`** added to imports
- **Fixed `datetime` import conflict** — removed bare `import datetime` module (was shadowing `from datetime import datetime, timedelta`)

#### From `enhance-clinic-crm` (extracted)
- **`inject_global_vars` context processor** — injects `unread_messages` count into all templates
- **`edit_note` route** (`POST /note/<id>/edit`) — admin can edit session note content, appearance, topics
- **Goals CRUD routes** — `add_goal` (`POST /patient/<id>/add_goal`) and `toggle_goal_status` (`POST /goal/<id>/toggle_status`)
- **Revenue dashboard** (`GET /admin/revenue`) — shows total revenue, pending debt, monthly breakdown; linked in admin navbar

### Files Changed
- `app.py` — added 5 new routes, 2 context processors, fixed datetime naming conflict
- `templates/admin_revenue.html` — new revenue dashboard template
- `templates/layout.html` — Revenue nav link added; notification toast container + polling script
- `templates/edit_patient.html` — better styled `can_self_schedule` toggle
- `schema.sql` — `notifications`, `goals`, `can_self_schedule` column added
- `requirements.txt` — added `psutil`, `python-docx`

---

## Session 2 — March 9, 2026 (Recurring Calendar Overhaul)

### Overview
Addressed the core recurring-appointment visibility problem: sessions belonging to long-running therapy patients were not appearing in the calendar. Also standardised both calendars to show only workdays (Sun–Thu) at the correct hours (08:00–20:00) with clean day-name-only column headers.

---

### 1. **Fixed Recurring Appointments Not Appearing in Calendar** ✅ — `app.py`

**Problem:**  
Recurring therapy sessions were invisible on any week that wasn't the week the series originally started. The entire projection loop was nested inside:

```python
if start_date <= original_appointment_date <= end_date:
    # project recurring occurrences  ← never reached for older series
```

Because most ongoing patients have series that began weeks or months ago, their original appointment date sits outside the current view window — so zero occurrences were ever projected and the calendar appeared empty.

**Root cause (secondary):**  
Even when the original date happened to fall in range, the projection iterated only `12 // interval_weeks` cycles *from the original date*, not from the current date, so bi-weekly series starting long ago would also be missed.

**Solution:**  
Completely rewrote the `/api/slots` endpoint recurring-event section (`app.py`):

- Fetches **all** recurring appointment series (not just those whose `appointment_date` falls in the view range).
- For each series, finds the Sunday of the week containing the original appointment and steps forward in `interval_weeks` increments, collecting every matching weekday occurrence.
- Stops walking only when the week's Sunday exceeds `end_date + 7 days` (no more occurrences can be in range).
- Applies `recurrence_end_date` and `recurrence_count` limits in the correct chronological order.
- Safety cap of 1040 week iterations (~20 years).

**How it works step by step:**
```
series_week_sunday = appt_date - timedelta(days=(appt_date.weekday()+1) % 7)
week_num = 0
while week_sunday <= end_date + 7 days:
    for each fc_day in recurrence_fc_days:       # 0=Sun, 1=Mon … 4=Thu
        occ = week_sunday + timedelta(days=fc_day)
        if occ >= appt_date: collect(occ)
    week_num += 1 (advance by interval_weeks)
apply limit_count / limit_date
emit events where start_date <= occ <= end_date
```

**Files Modified:** `app.py` — `api_slots()` function

---

### 2. **Fixed Recurring Event Titles** ✅ — `app.py`

**Problem:**  
All recurring occurrences were labelled `"Occupied (Recurring)"` regardless of who the patient was. This made it impossible to identify sessions on the admin calendar.

**Solution:**  
Applied the same title logic used for single appointments:
- **Admin view** → patient's name (e.g., `"Jane Cohen"`)
- **Patient view (own appointment)** → `"My Appointment"`
- **Patient view (other patient's slot)** → `"Occupied"`

**Files Modified:** `app.py` — `make_appt_event()` helper inside `api_slots()`

---

### 3. **Removed Dates from Calendar Column Headers** ✅ — Both calendars

**Problem:**  
Day column headers showed specific dates (e.g., "Mon 3/10"), which was noisy and inconsistent with the desired "weekly schedule" view that focuses on time slots rather than specific dates.

**Solution:**  
Added `dayHeaderFormat: { weekday: 'long' }` to both FullCalendar instances.  
Columns now read: **Sunday · Monday · Tuesday · Wednesday · Thursday**.

**Files Modified:** `templates/manage_slots.html`, `templates/dashboard.html`

---

### 4. **Standardised Calendar to Workdays and Correct Hours** ✅ — Both calendars

**Problem:**  
- Dashboard calendar showed Friday and Saturday (non-working days for this clinic).  
- Dashboard calendar cut off at **18:00** instead of the correct **20:00**.  
- Both calendars had mismatched configurations.

**Solution:**

| Setting | Before | After |
|---------|--------|-------|
| `hiddenDays` (dashboard) | not set (all 7 days shown) | `[5, 6]` (Fri + Sat hidden) |
| `slotMaxTime` (dashboard) | `18:00:00` | `20:00:00` |
| `firstDay` (dashboard) | not set | `0` (Sunday) |
| `headerToolbar center` | date range string | empty (no cluttered title) |

Admin (`manage_slots.html`) already had correct `hiddenDays` and hours; only the `dayHeaderFormat` and toolbar title were updated.

**Files Modified:** `templates/dashboard.html`, `templates/manage_slots.html`

---

### Files Modified — Session 2

| File | What Changed |
|------|-------------|
| `app.py` | Rewrote `api_slots()` recurring projection; fixed event titles |
| `templates/manage_slots.html` | `dayHeaderFormat`, removed center title |
| `templates/dashboard.html` | `hiddenDays`, `slotMaxTime`, `firstDay`, `dayHeaderFormat`, removed center title |
| `CHANGES.md` | This documentation |

---

### Testing Checklist — Session 2

1. **Recurring series started in the past shows on current week**  
   - Create a recurring weekly appointment starting 2+ months ago  
   - Navigate to the current week on `/admin/slots`  
   - ✅ Session must appear on the correct weekday

2. **Admin sees patient name on recurring events**  
   - Open `/admin/slots`, look at any recurring slot  
   - ✅ Title should be the patient's name, not "Occupied (Recurring)"

3. **Column headers show only weekday names**  
   - Open both `/admin/slots` and patient dashboard  
   - ✅ Columns should read "Sunday", "Monday", … — no numeric dates

4. **Dashboard shows Sun–Thu only, 08:00–20:00**  
   - Log in as a patient and open the dashboard  
   - ✅ Only five columns visible; time grid ends at 20:00

---

# Changes Documentation - 2026-04-09 08:19

## Overview

Optimized calendar blocking date operations to fix an N+1 query performance bottleneck.

## Changes Made

### 1. **Fixed N+1 Query in Blocking Dates** ✅
**Problem**: The `api_calendar_block` function in `app.py` executed individual `INSERT INTO blocked_slots` and `UPDATE slots_override` statements inside a `for block_day in dates_to_create:` loop, causing significant database roundtrip overhead when dealing with large recurrences.

**Solution**:
- Refactored the loop to gather tuples for inserts and updates into two lists using list comprehensions.
- Utilized `db.executemany` for batch inserting into `blocked_slots` and batch updating `slots_override`.
- Captured the current timestamp once before the lists generation to ensure precise consistency.
- Benchmarks demonstrated a ~24% improvement for 1000 items (0.0209s down to 0.0159s).

**Files Modified**: `app.py`

---

# Changes Documentation - March 9, 2026 (Session 1)

## Overview
Fixed multiple issues with ongoing patient crashes, color coding, calendar refresh, and unified booking interface.

## Changes Made

### 1. **Fixed Port Closing Issue in `run.py`** ✅
**Problem**: When Ctrl+C was pressed, the Flask app process wasn't properly terminating, causing the port (5000) to remain occupied.

**Solution**:
- Added `psutil` dependency for robust process management
- Implemented proper process group cleanup using `psutil.Process.children()`
- Added graceful termination with force-kill fallback
- Implemented proper signal handling with flag to prevent signal recursion
- Added auto-cleanup via `atexit` module for edge cases
- Added 0.5-second delay after process termination to ensure port release

**Files Modified**: `run.py`, `requirements.txt`

---

### 2. **Fixed Ongoing Patients Crash (Convert Modal)** ✅
**Problem**: The convert modal was missing critical fields (`duration`, `days`) causing form submission errors and crashes when converting candidates to ongoing.

**Solution**:
- Added `duration` field selector (30, 60, 90, 120 minutes)
- Added `days` checkboxes for recurrence day selection (Sun-Thu)
- Properly structure recurrence fields in modal  
- Enhanced error handling in `convert_patient()` function:
  - Input validation for dates and times
  - Type conversion with error handling
  - Database error handling with rollback
  - User-friendly error messages
  - Audit logging for patient conversion

**Files Modified**: `templates/patient_detail.html`, `app.py` (convert_patient function)

---

### 3. **Fixed Color Coding for Waiting Patients** ✅
**Problem**: Candidate and waiting patients were using the same color scheme, making it unclear which waiting patients have bookings scheduled.

**Solution**:
- Updated color logic to differentiate waiting patients:
  - `Ongoing` = Green (bg-success)
  - `Candidate` = Yellow (bg-warning)
  - `Waiting WITH recurring appointments` = Blue (bg-info) - indicates scheduled
  - `Waiting WITHOUT appointments` = Gray (bg-secondary) - indicates not yet scheduled
  - `Archived` = Gray (bg-secondary)

**Files Modified**: `templates/index.html`, `templates/patient_detail.html`

---

### 4. **Fixed Calendar Not Refreshing After Booking** ✅
**Problem**: After booking appointments from the patient detail page, the admin calendar in manage_slots didn't update automatically.

**Solution**:
- Added "Refresh" button to calendar toolbar
- Implemented auto-refresh every 30 seconds using `calendar.refetchEvents()`
- Calendar now properly reflects changes from both interfaces

**Files Modified**: `templates/manage_slots.html`

---

### 5. **Created Unified Booking Interface in Manage Slots** ✅
**Problem**: Booking existed in two disconnected places (patient detail vs. management tool) with different functionality. No way to book from scheduler tool.

**Solution**:
- Redesigned slot modal with dual modes:
  
  **Mode 1: Availability Management (Override)**
  - Manage slot availability (Open/Blocked/Occupied)
  - Set duration and status
  - Existing functionality preserved
  
  **Mode 2: Patient Booking**
  - Select patient from dropdown
  - Set appointment details (duration, cost, meeting type, link)
  - **RECURRING APPOINTMENT SUPPORT**:
    - Checkbox to enable recurring scheduling
    - Interval selection (weekly/bi-weekly)
    - Day of week selection
    - End limit options (by date or count)
  - Auto-marks slot as occupied after booking
  - Audit logging for admin actions

- Updated `manage_slots()` route:
  - Now passes all patients to template for dropdown
  
- Enhanced `admin_manage_slots()` function:
  - Detects mode and routes to appropriate handler
  - Comprehensive validation and error handling
  - Both single and recurring appointment support
  - Transaction rollback on errors
  - Automatic slot override creation/update

**Files Modified**: `templates/manage_slots.html`, `app.py`

---

### 6. **Enhanced Error Handling Throughout** ✅
- Added try-except blocks with proper error messages
- Implemented database transaction rollback on errors
- Improved validation for dates, times, and numeric fields
- User-friendly flash messages for all error conditions
- Audit logging for convert and booking operations

**Files Modified**: `app.py` (multiple functions)

---

## Testing Recommendations

### 1. **Ongoing Patient Conversion**
- Go to candidate patient
- Click "Convert to Ongoing"
- Fill all fields (should no longer crash):
  - Start date and time
  - Duration
  - Cost
  - Recurrence days (select at least Monday)
  - End limit (count or date)
- Verify patient converts successfully with audit log

### 2. **Patient Color Coding**
- View patients list (/patients)
- Verify colors:
  - Ongoing patients = Green
  - Candidate patients = Yellow
  - Waiting patients with recurring = Blue
  - Waiting patients without appointments = Gray

### 3. **Calendar Auto-Refresh**
- Open manage_slots in one window
- Book appointment from patient detail in another
- Verify calendar refreshes within 30 seconds
- Test manual "Refresh" button

### 4. **Unified Booking Interface**
- Go to Manage Slots
- Click on a time slot
- Switch between modes:
  - **Override Mode**: Manage availability
  - **Patient Booking Mode**: Book for patient
- Test booking single appointment
- Test booking with recurring option
- Verify slot is marked occupied
- Verify calendar updates

### 5. **Recurring Appointments from Scheduler**
- Book appointment from manage_slots
- Enable "Make recurring"
- Select interval (weekly/bi-weekly)
- Select days of week
- Set end limit (count or date)
- Verify recurring series appears in calendar

---

## Security Improvements
- Validated all user inputs (dates, times, numeric values)
- Protected against type errors and injection
- Proper authorization checks maintained
- Audit logging for sensitive operations

## Performance Improvements
- Calendar auto-refresh efficient (30-second intervals)
- Manual refresh button for immediate updates
- Better error isolation prevents cascading failures

## Backwards Compatibility
- All existing functionality preserved
- Can still use patient detail page for bookings
- Slot override management unchanged
- New booking interface is additive

---

## Files Modified Summary
1. `run.py` - Process management enhancements
2. `requirements.txt` - Added psutil
3. `app.py` - Multiple function improvements:
   - `manage_slots()` - Pass all_patients to template
   - `admin_manage_slots()` - Unified booking interface
   - `convert_patient()` - Complete rewrite with validation
   - `add_appointment()` - Recurring appointment support
   - `api_slots()` - Time handling improvements
   - `seed_data()` - Error handling
4. `templates/patient_detail.html` - Enhanced convert modal
5. `templates/index.html` - Improved color coding
6. `templates/manage_slots.html` - Unified booking modal + calendar refresh
7. `CHANGES.md` - Comprehensive documentation

# Changes Documentation - April 09, 2026

## Overview
Optimized performance of the patient data import functionality.

## Changes Made

### 1. **Optimized Patient Import Loop** ✅
**Problem**: The loop responsible for importing patient appointments was executing a `SELECT` database query for every individual appointment to check if it already exists. This resulted in an N+1 query problem, making the import process significantly slow for large files.

**Solution**:
- Pre-fetched all existing appointments for the target patient into a Python dictionary.
- Changed the loop logic to perform an O(1) dictionary lookup instead of a database query.
- Ensured newly imported appointments are dynamically added to the lookup dictionary within the loop to correctly handle potential duplicates within the imported data itself.
- Achieved a ~46% reduction in execution time for large imports as verified by benchmarks.

**Files Modified**: `app.py`
