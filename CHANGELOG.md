# Changelog

## [Unreleased] - 2026-06-25

### Fixed
- **UI:** Adjusted the sidebar width to prevent scrolling.
- **Data Loading:** Added functions to fetch all meeting notes and patient bookings.
- **Authenticator App:** Fixed a bug to prevent multiple form submissions on the login page.
- **Google Docs Integration:** Improved the error message for the Google Docs integration.
- **Testing:**
    - Fixed a `FileNotFoundError` in `test_app.py` by using an absolute path.
    - Fixed 3 failing tests in `test_google_oauth.py` related to Google Calendar integration settings.
    - Fixed `ModuleNotFoundError` in `test_import_clinic_data.py`, `test_export_data.py`, and `test_google_calendar.py` by correcting the `sys.path`.
    - Fixed a `sqlite3.OperationalError` in `test_patient_engagement.py` by properly initializing the test database.
    - Renamed benchmark scripts to prevent `pytest` collection errors.

### Known Issues
- One security test, `test_admin_smtp_health_endpoint_reports_not_configured`, is failing.
- The full test suite times out, indicating performance issues.
