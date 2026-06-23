# Instructions

## Route Structure
Route handlers live in `clinic_app/routes/*.py` as Flask blueprints:
- `health.py`, `patients.py`, `calendar.py`, `auth.py`, `billing.py`, `messaging.py`, `google_calendar.py`, `admin.py`
- Legacy `url_for()` endpoint names maintained via `app.add_url_rule()` aliases in `app.py`
- Shared utilities in `clinic_app/utils.py`; data helpers in `clinic_app/models.py`

## Running Tests
`python -m unittest discover -s tests -p 'test_*.py'`

### Environment variables required for tests
```powershell
$env:SECRET_KEY = "test-secret-key-for-testing-12345"
$env:FLASK_ENV = "development"
$env:TESTING = "1"
```

For Google OAuth tests also set:
```powershell
$env:GOOGLE_OAUTH_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
$env:GOOGLE_OAUTH_CLIENT_SECRET = "test-secret"
```

## Full Reference
See [docs/FULL_REFERENCE.md](docs/FULL_REFERENCE.md) for complete documentation on setup, deployment, security, design system, and more.
