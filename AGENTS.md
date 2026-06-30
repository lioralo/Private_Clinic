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
