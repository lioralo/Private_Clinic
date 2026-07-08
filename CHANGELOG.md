# Changelog

## [Unreleased] - 2026-07-08

### Added
- **Vacancy Update Endpoint:** `POST /api/calendar/vacancy/<id>/update` — updates vacant slot date, time, and recurrence pattern
- **CSRF JSON Error Handler:** 400 Bad Request errors now return JSON for `/api/` paths instead of HTML, preventing silent fetch failures from CSRF token expiry

### Fixed
- **Vacancy Edit Broken:** Replaced fragile modal-based edit flow with inline form-fill approach — clicking "edit" now populates the existing vacancy form and scrolls to it
- **Missing `.catch()` Handlers:** Added error handling to vacancy form submit, create-vacancy-from-slot, and book-slot-form — preventing silent failures leaving Bootstrap backdrops stuck
- **Google Docs Group Sync:** Moved `note_date` guard BEFORE session matching logic — items without dates are now skipped entirely instead of matching wrong sessions by title/position
- **Bootstrap Modal Backdrop:** Added persistent `hidden.bs.modal` listener that force-removes `.modal-backdrop` elements and resets body classes every time the modal hides, regardless of which code path triggered it
- **Google Docs Session Dates:** `session_date` now updated on existing group sessions when the document provides a date; title matching strips dates for accurate comparison
- **Google Sync Retries:** Added `database is locked` to transient error signals; increased retry from 3→5 attempts with 1s→2s base delay (62s total backoff)
- **Docker Volume:** Fixed compose project referencing wrong volume name after directory rename — restored production data (963 notes, 28 patients)

## [Unreleased] - 2026-07-05

### Added
- **Treatment Plans:** Structured treatment plans with SMART goals, diagnosis codes, problem statements, strengths, and progress tracking per goal. Full CRUD via dedicated blueprint (`/treatment-plans/`).
- **Clinical Assessments:** PHQ-9 (depression) and GAD-7 (anxiety) outcome measures with scoring engine, severity levels, and progress-over-time chart using Chart.js.
- **SMS Reminders:** Appointment SMS reminders via Twilio (optional). Per-patient toggle in edit form. Logs all attempts to `sms_logs` table. Scheduler runs alongside existing email reminders.
- **PWA Support:** `manifest.json` and `service-worker.js` for progressive web app install. Install button in sidebar. Caches static assets for offline access.
- **Alembic Migration:** `e7a2b9c4d1f0` — new tables `treatment_plans`, `treatment_plan_goals`, `assessment_types`, `assessments`, `sms_logs` + `reminder_sms_enabled` column on patients + PHQ-9/GAD-7 seed data.
- **Hebrew Translations:** ~90 new translation keys for treatment plans, assessments, SMS, and PWA.
- **Schema Refactor:** Unified `availability` table replacing `slots_override` and `vacancy_recurring`. Recurrence logic extracted to `recurring_occurrences_between` and `get_cancelled_dates` in `utils.py`.

### Fixed
- Tests updated to match refactored schema (`cancelled_dates` JSON array, `availability` table, removed `recurrence_interval`/`recurrence_days` from appointment queries).
- `test_fix_calendar_times.py` re-initializes DB state properly.

### Known Issues
- One security test, `test_admin_smtp_health_endpoint_reports_not_configured`, is failing.
- The full test suite times out, indicating performance issues.
