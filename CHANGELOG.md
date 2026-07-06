# Changelog

## [Unreleased] - 2026-07-05

### Added
- will-change: background-position added to skeleton shimmer for GPU acceleration
- **Treatment Plans:** Structured treatment plans with SMART goals, diagnosis codes, problem statements, strengths, and progress tracking per goal. Full CRUD via dedicated blueprint (`/treatment-plans/`).
- **Clinical Assessments:** PHQ-9 (depression) and GAD-7 (anxiety) outcome measures with scoring engine, severity levels, and progress-over-time chart using Chart.js.
- **SMS Reminders:** Appointment SMS reminders via Twilio (optional). Per-patient toggle in edit form. Logs all attempts to `sms_logs` table. Scheduler runs alongside existing email reminders.
- **PWA Support:** `manifest.json` and `service-worker.js` for progressive web app install. Install button in sidebar. Caches static assets for offline access.
- **Alembic Migration:** `e7a2b9c4d1f0` — new tables `treatment_plans`, `treatment_plan_goals`, `assessment_types`, `assessments`, `sms_logs` + `reminder_sms_enabled` column on patients + PHQ-9/GAD-7 seed data.
- **Hebrew Translations:** ~90 new translation keys for treatment plans, assessments, SMS, and PWA.
- **Schema Refactor:** Unified `availability` table replacing `slots_override` and `vacancy_recurring`. Recurrence logic extracted to `recurring_occurrences_between` and `get_cancelled_dates` in `utils.py`.
- **Clean Design System:** Minimalist design with Poppins/Roboto typography, blue primary (#3B82F6), 8pt baseline grid. See DESIGN.md.
- **RTL Icons:** Automatic icon mirroring for Hebrew locale via CSS `html[dir="rtl"]` transforms.
- **SendGrid v3 API:** Email sending now uses the SendGrid HTTP API (not raw SMTP) with proper DKIM signing and error reporting. Fallback to SMTP for non-SendGrid providers.

### Fixed
- transition-all replaced with specific transition-* classes across all templates and App.tsx for perf
- Tests updated to match refactored schema (`cancelled_dates` JSON array, `availability` table, removed `recurrence_interval`/`recurrence_days` from appointment queries).
- `test_fix_calendar_times.py` re-initializes DB state properly.
- `admin_smtp_test` route redirects with flash message instead of returning raw JSON.
- SMTP email headers now include proper Message-ID, Date, Reply-To, and display name.
- Domain `clinic.lior-clinic.org` authenticated in SendGrid (3 CNAME records in IONOS) — resolves Gmail DMARC rejection.

### Known Issues
- One security test, `test_admin_smtp_health_endpoint_reports_not_configured`, is failing.
- The full test suite times out, indicating performance issues.
