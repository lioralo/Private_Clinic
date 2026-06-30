# Deployment Guide

## Prerequisites

- Docker & Docker Compose (on the EC2 instance)
- Domain `clinic.lior-clinic.org` managed at IONOS
- AWS SES (eu-north-1) verified + SMTP credentials (see `.env.prod.example`)

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Builds the app container (Python 3.12, Gunicorn) |
| `docker-compose.prod.yml` | Production stack: app + Caddy reverse proxy |
| `Caddyfile` | Caddy config with auto TLS via Let's Encrypt |
| `wsgi.py` | Entry point (calls `ensure_runtime_paths()` + `init_db()`) |
| `.env` | **Secret config file** — NOT committed to git (in `.gitignore`) |
| `.env.prod.example` | Template for `.env` with all supported variables |

## Data Persistence (IMPORTANT)

> **All data (database, uploads, backups, encryption keys) is stored in a Docker named volume `clinic_clinic_app_data`.**
> **This volume persists independently of the repo directory — data survives `git pull`, rebuilds, and even `docker compose down`.**

### How it works

The `docker-compose.prod.yml` mounts the named volume `clinic_app_data` (Docker auto-prefixes it as `clinic_clinic_app_data`) at `/data` inside the container.
This contains:

| Container path | Content | Persists on update? |
|----------------|---------|---------------------|
| `/data/clinic.db` | SQLite database (users, patients, appointments, settings, 2FA secrets, Google tokens) | ✅ |
| `/data/uploads/` | Patient uploaded files | ✅ |
| `/data/patients_logs/` | Session logs | ✅ |
| `/data/secure_backups/` | Encrypted daily backups | ✅ |
| `/data/.clinic_keys/` | Backup encryption keys | ✅ |
| `/data/app_log.txt` | Application logs | ✅ |

### What survives an update

All of the following survive when you run `git pull && docker compose up -d --build`:
- **Database** (patients, appointments, notes, billing)
- **Users and passwords** (admin + patients)
- **2FA/TOTP configuration**
- **Google OAuth tokens** (Calendar, Docs integration)
- **Site settings**
- **Uploaded files and patient logs**
- **Encrypted backup history**

### ⚠️ What does NOT create a new database

The app only creates a new admin user if `clinic.db` does not exist in the volume.
If the volume already has a database (from a previous deployment), the app uses it as-is.

## Step-by-Step Deployment

### 1. Clone the repo on the EC2 instance

Clone to ANY directory — data lives in the Docker volume, not in the repo:

```bash
ssh -i your-key.pem ubuntu@<ec2-public-ip>
git clone <repo-url> clinic
cd clinic
```

### 2. Create the `.env` file

```bash
cp .env.prod.example .env
nano .env
```

Fill in with your real values:

| Variable | Value |
|----------|-------|
| `DOMAIN` | `clinic.lior-clinic.org` |
| `SECRET_KEY` | long random string (>32 chars) |
| `TLS_EMAIL` | your email for Let's Encrypt cert |
| `BACKUP_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GOOGLE_CLIENT_ID` | from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | from Google Cloud Console |
| `SMTP_HOST` | `email-smtp.eu-north-1.amazonaws.com` |
| `SMTP_USERNAME` | SES SMTP username (from admin_credentials.csv) |
| `SMTP_PASSWORD` | SES SMTP password (from admin_credentials.csv) |
| `SMTP_FROM_EMAIL` | `admin@clinic.lior-clinic.org` |
| `SESSION_COOKIE_SECURE` | `1` (required for HTTPS) |

### 3. Start the stack

```bash
docker compose -f docker-compose.prod.yml up -d
```

### 4. Verify

```bash
# Check running containers
docker ps

# Follow the logs
docker compose -f docker-compose.prod.yml logs -f

# Health check
curl https://clinic.lior-clinic.org/healthz
```

### 5. DNS (IONOS)

Set these A records at https://my.ionos.com → Domain → `clinic.lior-clinic.org`:

| Type | Host | Value |
|------|------|-------|
| A | `clinic.lior-clinic.org` | your EC2 public IP |
| A | `www.clinic.lior-clinic.org` | your EC2 public IP (or CNAME to `clinic.lior-clinic.org`) |

Also add the SES DKIM CNAME records as described in `.env.prod.example`.

### 6. Initial Admin Login

- URL: `https://clinic.lior-clinic.org`
- Default username: `admin`
- Default password: generated on first start (check `docker compose logs app` for "Temporary password")

**Change the password immediately after first login.**

## Updating (Data-Safe)

```bash
cd clinic
git pull
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d app
```

**The Docker volume `clinic_clinic_app_data` preserves all data across updates.**
`docker compose down` does NOT remove named volumes (only `docker compose down -v` does).
If you accidentally run `docker compose down -v`, restore from the latest backup in the Admin panel.

## Backup

Backups are automatically encrypted to `/data/secure_backups/` (inside the Docker volume) every 12 hours.
Manual backup available at: Admin Dashboard → Backup/Restore.

### Restoring from backup in disaster recovery

If the volume is lost (e.g., `docker compose down -v` was run):

1. Create a fresh volume: `docker volume create clinic_app_data`
2. Copy your latest `.db.enc` backup file into `/var/lib/docker/volumes/clinic_clinic_app_data/_data/secure_backups/`
3. Start the stack
4. Go to Admin Dashboard → Backup/Restore → select the backup file → Restore

## Troubleshooting

| Problem | Check |
|---------|-------|
| App not starting | `docker compose logs app` |
| SSL cert not issuing | Ensure A record points to this server, port 80/443 open in EC2 security group |
| Emails not sending | `curl https://clinic.lior-clinic.org/admin/smtp/health` (needs admin login) |
| SES emails rejected | Request production access in SES console (sandbox can only send to verified addresses) |

## New Features in This Version

- **Appointment reminders** via AWS SES (automated, 24h before)
- **Appointment change notifications** (cancel/reschedule → email + internal message)
- **Per-appointment reminder timing** (set `reminder_hours_before` per appointment)
- **Incoming email polling** (optional IMAP — replies to automated emails appear in patient messaging)
- **Reminder audit log** (`reminder_log` table for full send history)
- **Patient preference toggle** for email reminders
