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

## Deployment (Data Persistence)

### Docker volumes for data persistence

The production stack (`docker-compose.prod.yml`) uses a **named Docker volume** for all persistent data:

| Volume | Mount | Content |
|--------|-------|---------|
| `clinic_app_data` (→ `clinic_clinic_app_data`) | `/data` | DB, uploads, logs, backups, encryption keys |

**The volume persists across:**
- `git pull` + rebuild
- `docker compose down` (volumes are NOT removed by default)
- Cloning the repo to a different directory

**What is NOT lost on redeployment:**
- Database (patients, appointments, notes, billing)
- Users, passwords, 2FA/TOTP setup
- Google OAuth tokens
- Site settings
- Uploaded files and patient logs
- Backup history

### Updating safely

```bash
cd clinic
git pull
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d app
```

### ⚠️ Never run `docker compose down -v`

The `-v` flag removes named volumes and destroys all data.
If accidentally run, restore from the latest encrypted backup via Admin Dashboard → Backup/Restore.

### First-time migration from bind-mount to volume

If the old deployment used `./data:/data` (bind mount), migrate to the named volume:

```bash
# Stop old stack
docker compose down

# Create the named volume
docker volume create clinic_app_data

# Copy existing data into the volume
sudo cp -a /path/to/old/data/. /var/lib/docker/volumes/clinic_clinic_app_data/_data/

# Edit docker-compose.prod.yml: change `./data:/data` to `clinic_app_data:/data`
# Start the stack
docker compose up -d
```

## Full Reference
See [docs/FULL_REFERENCE.md](docs/FULL_REFERENCE.md) for complete documentation on setup, deployment, security, design system, and more.

## Cursor Cloud specific instructions

This is a single self-contained Flask app (`app.py`) backed by embedded SQLite — no external DB/services are required to run or test. The environment is Linux/bash (docs above use PowerShell). The startup update script already installs Python deps (into system Python via `pip install --break-system-packages`, because `python3-venv` is not available here) plus `pytest` (which is not in `requirements.txt`). Env vars: use bash `export VAR=value` instead of the PowerShell `$env:` syntax shown above.

### Running the dev server
- Start with `python3 app.py` (dev server on port 5000, auto-falls back to the next free port; override with `PORT`). `run.py` is an alternative wrapper.
- `SECRET_KEY` must be **at least 32 characters** or `app.py` refuses to start (`RuntimeError`).
- Do **not** run the dev server against the git-tracked `clinic.db` (writes would dirty a tracked file). Point `DATABASE` at a throwaway path, e.g. `export DATABASE=/workspace/clinic_dev.db` (any `*.db` except `clinic.db` is git-ignored).
- Admin bootstrap only happens on **first** init of a fresh DB: set `ADMIN_USERNAME` / `ADMIN_PASSWORD` beforehand, otherwise a random temp password is printed to stdout and a forced password change is set.
- Harmless startup warnings you can ignore on a fresh dev DB: `BACKUP_ENCRYPTION_KEY not set` and `Routine backup skipped: no such column: recurrence_days`.

### Schema gotcha (important)
`init_db()` only auto-applies Alembic migrations when the DB **already** contains an `alembic_version` table. A brand-new DB built only from `schema.sql` + `_run_db_migrations()` will be **missing tables added by later Alembic revisions** (e.g. `assessments`, `treatment_plans`), which causes `sqlite3.OperationalError: no such table` at runtime. To build a complete fresh dev DB, run `DATABASE=/workspace/clinic_dev.db python3 -m alembic upgrade heads` (note: **`heads`**, plural — the migration graph has multiple heads) before starting the app.

### Tests & lint
- Test command is documented above (`python -m pytest tests/ -q`, with `SECRET_KEY` / `FLASK_ENV` / `TESTING` set). ~291 pass. A large batch of failures is **pre-existing and not environment-related**: the test harness (`tests/test_app.py` `setUp`) builds its DB from `schema.sql` + `_run_db_migrations()` only (no Alembic), so Alembic-only tables (`assessments`, `treatment_plans`) are missing, and some tests hit outdated routes (e.g. they GET `/logout`, which is now POST-only → 405).
- There is no configured linter (no flake8/ruff/pylint). The closest guardrail is the route-contract check: `python verification/refactor_guard.py check`.
