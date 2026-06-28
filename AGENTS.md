# Instructions

## Route Structure
Route handlers live in `clinic_app/routes/*.py` as Flask blueprints:
- `health.py`, `patients.py`, `calendar.py`, `auth.py`, `billing.py`, `messaging.py`, `google_calendar.py`, `admin.py`
- Legacy `url_for()` endpoint names maintained via `app.add_url_rule()` aliases in `app.py`
- Shared utilities in `clinic_app/utils.py`; data helpers in `clinic_app/models.py`
- Google OAuth setup wizard at `/admin/google-setup` (endpoint: `admin.google_setup`)

## Database Migrations (Alembic)
Schema migrations use Alembic. Two revisions capture the full schema:

| Revision | Description |
|----------|-------------|
| `8dcaf298fef3` | Initial tables from `schema.sql` |
| `32d4a8bb1807` | All tables, columns & indexes from `_run_db_migrations()` |

- `_run_db_migrations()` is skipped when `alembic_version` exists (Alembic-managed DB).
- Existing DBs are stamped at `head` automatically after `init_db()` completes.
- Skipped during testing (`TESTING=True`).
- To create a new migration for future schema changes:
  ```powershell
  alembic revision -m "description_of_change"
  ```
  Then edit the generated file with `op.execute(...)` calls.
- To apply pending migrations (e.g., on a fresh clone):
  ```powershell
  alembic upgrade head
  ```
- **For new schema changes:** do NOT add to `_run_db_migrations`. Create an Alembic revision instead.

## Running Tests
`python -m pytest tests/ -q`

### Environment variables required for tests
```powershell
$env:SECRET_KEY = "test-secret-key-for-testing-12345"
$env:FLASK_ENV = "development"
$env:TESTING = "1"
```

For Google OAuth tests also set:
```powershell
$env:GOOGLE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
$env:GOOGLE_CLIENT_SECRET = "test-secret"
```

## Full Reference
See [docs/FULL_REFERENCE.md](docs/FULL_REFERENCE.md) for complete documentation on setup, deployment, security, design system, and more.
