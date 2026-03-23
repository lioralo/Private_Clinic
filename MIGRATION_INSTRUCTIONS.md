# Private Clinic – Beta → Production Migration Guide

This document provides a step-by-step runbook for migrating the Private Clinic application
from a beta/staging server to a live production environment.

**Estimated total migration window:** 30–60 minutes (plus any DNS propagation time)  
**Required downtime:** ~5–15 minutes during Phase 4 (live server restoration)

---

## Prerequisites

| Item | Where to find it |
|------|-----------------|
| SSH access to **beta** server | Your DevOps team / AWS console |
| SSH access to **live** server | Your DevOps team / AWS console |
| Production `.env.prod` values | See `LIVE_DEPLOYMENT.md` for generation instructions |
| `BACKUP_ENCRYPTION_KEY` value from beta | Beta server `.env.prod` or `secure_backups/.backup.key` |
| `scp`/`rsync` available on both hosts | Standard Ubuntu install |
| Docker + Docker Compose on live server | `scripts/setup_ubuntu_docker.sh` |

> **Security note:** all commands that handle secrets are shown with placeholder values in
> angle brackets, e.g. `<BETA_ENCRYPTION_KEY>`.  Replace every placeholder with the real
> value before running.

---

## Phase 1 – Pre-Migration Checklist

Complete every item on this checklist **before** beginning the migration.

### 1.1 Verify the backup encryption key on the beta server

```bash
# SSH into beta server
ssh ubuntu@<BETA_SERVER_IP>

cd /opt/private_clinic        # or wherever the repo is deployed

# Option A – key stored in .env.prod
grep BACKUP_ENCRYPTION_KEY .env.prod

# Option B – key stored in the fallback file
cat data/secure_backups/.backup.key
```

Save the key value in a secure password manager entry labelled **"Beta Backup Encryption Key"**.
You will need it in Phase 4.

### 1.2 Confirm admin credentials

```bash
# On the beta server – open a one-off Python shell inside the running container
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec app python3 - <<'PY'
import sqlite3, os
db = sqlite3.connect(os.environ.get("DATABASE", "/data/clinic.db"))
rows = db.execute("SELECT id, username, role, totp_enabled FROM users WHERE role='admin'").fetchall()
for r in rows:
    print(r)
PY
```

Note every admin username and confirm you know the password for at least one account.

### 1.3 Database integrity check on beta

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec app python3 - <<'PY'
import sqlite3, os
db = sqlite3.connect(os.environ.get("DATABASE", "/data/clinic.db"))
result = db.execute("PRAGMA integrity_check").fetchone()
print("Integrity:", result)
print("Page count:", db.execute("PRAGMA page_count").fetchone())
PY
```

Expected output: `Integrity: ('ok',)`

If integrity check fails, **stop the migration** and investigate before continuing.

### 1.4 Row-count baseline (record before migrating)

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec app python3 - <<'PY'
import sqlite3, os
db = sqlite3.connect(os.environ.get("DATABASE", "/data/clinic.db"))
tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for (t,) in sorted(tables):
    count = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    if count:
        print(f"  {t}: {count} rows")
PY
```

Save this output – you will compare it against the live server in Phase 5.

### 1.5 Network connectivity validation

```bash
# From your workstation – confirm you can reach both servers
ssh -o ConnectTimeout=10 ubuntu@<BETA_SERVER_IP>  "echo beta OK"
ssh -o ConnectTimeout=10 ubuntu@<LIVE_SERVER_IP>  "echo live OK"

# Confirm the live server can accept SCP transfers
ssh ubuntu@<LIVE_SERVER_IP> "df -h /opt"
```

---

## Phase 2 – Beta Server Extraction

All commands in this phase run on the **beta server**.

### 2.1 Create a fresh encrypted backup

Log in to the beta server:

```bash
ssh ubuntu@<BETA_SERVER_IP>
cd /opt/private_clinic
```

Trigger a manual backup via the app's built-in backup endpoint (recommended):

```bash
# Log in and save the session cookie jar
curl -s -c /tmp/jar.txt -b /tmp/jar.txt -X POST \
  -d "username=<ADMIN_USER>&password=<ADMIN_PASS>" \
  https://<BETA_DOMAIN>/login -o /dev/null

# Trigger the backup using the saved cookie jar
curl -s -b /tmp/jar.txt -X POST https://<BETA_DOMAIN>/admin/backup_now
```

Alternatively, trigger the backup directly inside the container:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec app python3 - <<'PY'
import os, sys
sys.path.insert(0, '/app')
from app import perform_encrypted_backup
db_path = os.environ.get("DATABASE", "/data/clinic.db")
result = perform_encrypted_backup(db_path)
print("Backup result:", result)
PY
```

### 2.2 Identify and verify the backup file

```bash
ls -lh data/secure_backups/clinic_*.db.enc | tail -5
```

Note the filename of the newest `.db.enc` file, e.g. `clinic_20260321_180000.db.enc`.

Verify the backup can be decrypted without errors:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec app python3 - <<'PY'
import os, sys, zipfile, io
sys.path.insert(0, '/app')
from cryptography.fernet import Fernet

backup_dir = os.environ.get("BACKUP_DIR", "/data/secure_backups")
key_env    = os.environ.get("BACKUP_ENCRYPTION_KEY")
key_file   = os.path.join(backup_dir, ".backup.key")
key = key_env.encode() if key_env else open(key_file, "rb").read()
fernet = Fernet(key)

files = sorted(f for f in os.listdir(backup_dir) if f.endswith(".db.enc"))
latest = files[-1]
data = open(os.path.join(backup_dir, latest), "rb").read()
raw  = fernet.decrypt(data)
zf   = zipfile.ZipFile(io.BytesIO(raw))
print("Backup members:", zf.namelist()[:10])
print("Verification: OK –", latest)
PY
```

### 2.3 Extract the encryption key

```bash
# Read from environment file
grep BACKUP_ENCRYPTION_KEY .env.prod > /tmp/beta_key.txt

# Or from the fallback key file
cp data/secure_backups/.backup.key /tmp/beta_backup.key
```

> **Store both files securely.**  You must provide the same key on the live server so it can
> decrypt the backup bundle.

### 2.4 Inventory all artifacts to transfer

```bash
echo "=== Database backup file ==="
ls -lh data/secure_backups/clinic_*.db.enc | tail -1

echo "=== Uploads directory ==="
du -sh data/uploads/ 2>/dev/null || echo "(empty)"

echo "=== Patient logs ==="
du -sh data/patients_logs/ 2>/dev/null || echo "(empty)"

echo "=== Application log ==="
ls -lh data/app_log.txt 2>/dev/null || echo "(not present)"
```

---

## Phase 3 – Data Transfer

All commands in this phase run **from your workstation** (or from the live server pulling
from beta).

### 3.1 Create a staging directory on the live server

```bash
ssh ubuntu@<LIVE_SERVER_IP> "mkdir -p /tmp/migration/{backup,uploads,logs}"
```

### 3.2 Transfer the encrypted backup

```bash
# Identify the latest backup filename on beta
BACKUP_FILE=$(ssh ubuntu@<BETA_SERVER_IP> \
  "ls /opt/private_clinic/data/secure_backups/clinic_*.db.enc | sort | tail -1")

echo "Transferring: $BACKUP_FILE"

scp ubuntu@<BETA_SERVER_IP>:"$BACKUP_FILE" \
    ubuntu@<LIVE_SERVER_IP>:/tmp/migration/backup/
```

### 3.3 Transfer the encryption key

```bash
# Copy the key from beta to live – do this over SSH, not email/Slack
ssh ubuntu@<BETA_SERVER_IP> "grep BACKUP_ENCRYPTION_KEY /opt/private_clinic/.env.prod" \
  | ssh ubuntu@<LIVE_SERVER_IP> "cat > /tmp/migration/backup/beta_key.env"
```

### 3.4 Transfer uploads

```bash
rsync -avz --progress \
  ubuntu@<BETA_SERVER_IP>:/opt/private_clinic/data/uploads/ \
  ubuntu@<LIVE_SERVER_IP>:/tmp/migration/uploads/
```

### 3.5 Transfer patient logs

```bash
rsync -avz --progress \
  ubuntu@<BETA_SERVER_IP>:/opt/private_clinic/data/patients_logs/ \
  ubuntu@<LIVE_SERVER_IP>:/tmp/migration/logs/
```

### 3.6 Transfer application log (optional – for audit continuity)

```bash
scp ubuntu@<BETA_SERVER_IP>:/opt/private_clinic/data/app_log.txt \
    ubuntu@<LIVE_SERVER_IP>:/tmp/migration/app_log.txt
```

### 3.7 Verify transferred files on live server

```bash
ssh ubuntu@<LIVE_SERVER_IP> <<'EOF'
echo "=== Backup file ==="
ls -lh /tmp/migration/backup/*.db.enc

echo "=== Key file ==="
cat /tmp/migration/backup/beta_key.env

echo "=== Uploads ==="
find /tmp/migration/uploads -type f | wc -l

echo "=== Patient logs ==="
find /tmp/migration/logs -type f | wc -l
EOF
```

Compare file counts against the inventory recorded in Phase 2.4.

---

## Phase 4 – Live Server Restoration

All commands in this phase run on the **live server**.

> ⚠️ **This phase causes downtime.**  Notify users before proceeding.

### 4.1 Prepare the live server environment

```bash
ssh ubuntu@<LIVE_SERVER_IP>
cd /opt/private_clinic       # repo must already be deployed per LIVE_DEPLOYMENT.md
```

Ensure `.env.prod` exists and contains the **beta** encryption key so that the restore
function can decrypt the transferred backup:

```bash
# Extract the key value from the transferred key file
BETA_KEY=$(grep BACKUP_ENCRYPTION_KEY /tmp/migration/backup/beta_key.env \
           | cut -d= -f2-)

# Update (or set) BACKUP_ENCRYPTION_KEY in the live .env.prod
if grep -q "^BACKUP_ENCRYPTION_KEY=" .env.prod; then
    sed -i "s|^BACKUP_ENCRYPTION_KEY=.*|BACKUP_ENCRYPTION_KEY=${BETA_KEY}|" .env.prod
else
    echo "BACKUP_ENCRYPTION_KEY=${BETA_KEY}" >> .env.prod
fi

echo "Key set. Verifying..."
grep BACKUP_ENCRYPTION_KEY .env.prod
```

### 4.2 Copy backup and artifacts into the data volume

```bash
# Ensure data directories exist
mkdir -p data/secure_backups data/uploads data/patients_logs

# Move the encrypted backup into the backup directory
cp /tmp/migration/backup/*.db.enc data/secure_backups/

# Copy uploads (merge into existing directory if any)
rsync -a /tmp/migration/uploads/ data/uploads/

# Copy patient logs
rsync -a /tmp/migration/logs/ data/patients_logs/

# Copy application log (appended for audit continuity)
if [ -f /tmp/migration/app_log.txt ]; then
    cat /tmp/migration/app_log.txt >> data/app_log.txt
fi

echo "Artifacts copied:"
ls -lh data/secure_backups/*.db.enc
```

### 4.3 Stop the running Docker stack (begin downtime)

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down
```

### 4.4 Restore the database from the encrypted backup

Start a temporary container with the data volume mounted and run the built-in restore:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm app python3 - <<'PY'
import os, sys, sqlite3, zipfile, io, shutil, datetime
sys.path.insert(0, '/app')
from cryptography.fernet import Fernet

backup_dir  = os.environ.get("BACKUP_DIR",  "/data/secure_backups")
db_path     = os.environ.get("DATABASE",    "/data/clinic.db")
key_env     = os.environ.get("BACKUP_ENCRYPTION_KEY")
key_file    = os.path.join(backup_dir, ".backup.key")

key    = key_env.encode() if key_env else open(key_file, "rb").read()
fernet = Fernet(key)

files  = sorted(f for f in os.listdir(backup_dir) if f.endswith(".db.enc"))
if not files:
    print("ERROR: no backup files found in", backup_dir)
    sys.exit(1)

latest = files[-1]
print("Restoring from:", latest)
data   = open(os.path.join(backup_dir, latest), "rb").read()
raw    = fernet.decrypt(data)
zf     = zipfile.ZipFile(io.BytesIO(raw))

# Safety copy of any existing database
if os.path.exists(db_path):
    ts  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, f"clinic_pre_restore_{ts}.db")
    shutil.copy2(db_path, dst)
    print("Pre-restore safety copy saved to:", dst)

# Extract database
zf.extract("clinic.db", "/tmp/restore_staging")
staging_db = "/tmp/restore_staging/clinic.db"

# Integrity check on extracted database
conn = sqlite3.connect(staging_db)
result = conn.execute("PRAGMA integrity_check").fetchone()
conn.close()
if result != ("ok",):
    print("ERROR: extracted database failed integrity check:", result)
    sys.exit(1)

# Replace live database
shutil.move(staging_db, db_path)
print("Database restored and verified: PRAGMA integrity_check =", result)

# Restore uploads if present in bundle
upload_folder = os.environ.get("UPLOAD_FOLDER", "/data/uploads")
for member in zf.namelist():
    if member.startswith("uploads/"):
        zf.extract(member, "/data")
        print("Restored upload:", member)

# Restore patient logs if present in bundle
logs_folder = os.environ.get("PATIENT_LOGS_FOLDER", "/data/patients_logs")
for member in zf.namelist():
    if member.startswith("patients_logs/"):
        zf.extract(member, "/data")
        print("Restored log:", member)

print("Restore complete.")
PY
```

### 4.5 Bring the live stack back up (end downtime)

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Wait ~20 seconds, then confirm the services are healthy:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=50 app
```

Expected: both `app` and `caddy` services show `Up` or `running` status and the log shows
`init_db` completing without errors.

### 4.6 Post-restore database integrity check

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec app python3 - <<'PY'
import sqlite3, os
db = sqlite3.connect(os.environ.get("DATABASE", "/data/clinic.db"))
print("Integrity:", db.execute("PRAGMA integrity_check").fetchone())
tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for (t,) in sorted(tables):
    count = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    if count:
        print(f"  {t}: {count} rows")
PY
```

Compare row counts against the baseline recorded in Phase 1.4.

---

## Phase 5 – Post-Migration Validation

### 5.1 Data completeness verification

Using the row-count baseline from Phase 1.4, confirm every table shows the same (or
greater) count on the live server.

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec app python3 - <<'PY'
import sqlite3, os
db = sqlite3.connect(os.environ.get("DATABASE", "/data/clinic.db"))
tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print(f"{'Table':<35} {'Rows':>8}")
print("-" * 45)
for (t,) in sorted(tables):
    count = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t:<33} {count:>8}")
PY
```

### 5.2 User authentication test

1. Open `https://<LIVE_DOMAIN>/login` in a browser.
2. Log in with an admin account.
3. If TOTP is enabled, confirm the authenticator app produces a valid code.
4. Confirm you can reach `/admin/dashboard` without errors.

### 5.3 Patient and appointment data checks

In the admin dashboard:

- Navigate to **Patients** and confirm patient records are visible.
- Navigate to **Appointments** and confirm upcoming appointments are listed.
- Open one patient record and confirm attachments/uploads are accessible.

### 5.4 Upload accessibility check

```bash
# List uploaded files visible through the web server
curl -I https://<LIVE_DOMAIN>/static/uploads/ 2>&1 | head -5
# Alternatively, check the data volume directly
ls data/uploads/ | head -20
```

### 5.5 Log integrity validation

```bash
# Application log should contain recent entries
tail -30 data/app_log.txt

# Patient logs directory should be populated
ls data/patients_logs/ | wc -l
```

### 5.6 Automatic backup health check

Confirm the routine backup mechanism is working after the first request:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs app 2>&1 \
  | grep -i backup | tail -10

ls -lh data/secure_backups/
cat data/secure_backups/.last_backup_at 2>/dev/null || echo "(not yet written)"
```

---

## Phase 6 – Operational Handoff

### 6.1 Reset the admin password on the live server

> Change the default or beta admin password immediately after migration.

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec app python3 - <<'PY'
import sqlite3, os, getpass
from werkzeug.security import generate_password_hash

NEW_PASSWORD = getpass.getpass("Enter new admin password: ")
hashed = generate_password_hash(NEW_PASSWORD)
db = sqlite3.connect(os.environ.get("DATABASE", "/data/clinic.db"))
db.execute("UPDATE users SET password_hash=?, force_password_change=0 WHERE role='admin'",
           (hashed,))
db.commit()
print("Admin password updated.")
PY
```

### 6.2 Set up TOTP authenticator for admin accounts

1. Log in to `https://<LIVE_DOMAIN>/login` as admin.
2. Navigate to **Admin → Setup Authenticator** (`/admin/setup_authenticator`).
3. Scan the QR code with an authenticator app (Google Authenticator, Authy, etc.).
4. Enter the 6-digit code to confirm and activate 2FA.
5. Repeat for every admin account.

### 6.3 Rotate the encryption key (recommended)

After a successful migration, generate a fresh encryption key for the live server so it is
independent of the beta key:

```bash
# Generate a new key
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Update .env.prod on the live server with the new key
# Then create a fresh backup (which will use the new key going forward)
```

> **Important:** existing `.db.enc` files were created with the beta key.  Keep the beta key
> in a secure store until all old backup files are rotated out.  The new key applies only to
> backups created *after* the key rotation.

### 6.4 Access control verification

```bash
# Confirm no patient-facing routes are accessible without login
curl -s -o /dev/null -w "%{http_code}" https://<LIVE_DOMAIN>/admin/dashboard
# Expected: 302 (redirect to login)

curl -s -o /dev/null -w "%{http_code}" https://<LIVE_DOMAIN>/
# Expected: 200 or 302 (depends on login state)
```

### 6.5 Monitoring and alerts

Recommended checks to set up once the application is live:

| Check | How |
|-------|-----|
| Uptime / HTTP health | Pingdom, UptimeRobot, or AWS Route 53 health checks against `https://<LIVE_DOMAIN>/` |
| Disk usage | CloudWatch agent or cron: `df -h /opt/private_clinic/data` |
| Backup freshness | Daily cron: check `data/secure_backups/.last_backup_at` is within 24 h |
| Container status | `docker compose ps` scheduled alert via cron |
| TLS certificate | Caddy renews automatically; verify with `curl -vI https://<LIVE_DOMAIN> 2>&1 | grep expire` |

Example cron for backup-age alert (`crontab -e` on the live server):

```cron
0 * * * * TIMESTAMP_FILE=/opt/private_clinic/data/secure_backups/.last_backup_at; \
  if [ ! -f "$TIMESTAMP_FILE" ]; then \
    echo "No backup timestamp found" | mail -s "Clinic backup alert" admin@example.com; \
  else \
    LAST=$(cat "$TIMESTAMP_FILE"); NOW=$(date +%s); \
    AGE=$(( NOW - LAST )); \
    [ "$AGE" -gt 86400 ] && echo "Last backup is over 24 h old (${AGE}s ago)" \
      | mail -s "Clinic backup alert" admin@example.com; \
  fi
```

---

## Troubleshooting

### Encrypted backup cannot be decrypted

**Symptom:** `cryptography.fernet.InvalidToken` error during restore.

**Cause:** The `BACKUP_ENCRYPTION_KEY` on the live server does not match the key used to
create the backup on beta.

**Resolution:**

```bash
# Verify the key currently set on the live server
grep BACKUP_ENCRYPTION_KEY /opt/private_clinic/.env.prod

# Compare to the key extracted from beta (Phase 2.3)
cat /tmp/migration/backup/beta_key.env
```

Ensure both values are identical (no trailing whitespace or newline differences).

---

### Docker container fails to start after restore

**Symptom:** `docker compose ps` shows container in `Exit` state.

**Resolution:**

```bash
# View the last 100 log lines
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 app

# Common causes:
# 1. Missing environment variable – check .env.prod is complete
# 2. Database permission issue – check ownership
ls -la data/clinic.db

# Fix ownership if needed
sudo chown $USER:$USER data/clinic.db
```

---

### Database integrity check fails

**Symptom:** `PRAGMA integrity_check` returns something other than `ok`.

**Resolution:**

```bash
# List available backup files with timestamps to choose from
ls -lh data/secure_backups/clinic_*.db.enc

# Identify which backup you want to restore (files are named clinic_YYYYMMDD_HHMMSS.db.enc)
# Then modify the restore script in Phase 4.4 to target that specific file, e.g.:
files = sorted(f for f in os.listdir(backup_dir) if f.endswith(".db.enc"))
# Choose by index: -1 = latest, -2 = second-latest, etc.
# Or specify directly:
latest = "clinic_20260321_120000.db.enc"   # replace with the desired filename
```

---

### Uploads not visible after restore

**Symptom:** Uploaded files return 404 in the browser.

**Cause:** `rsync` in Phase 3.4 may not have completed, or the `UPLOAD_FOLDER` environment
variable points to a different path.

**Resolution:**

```bash
# Confirm the upload folder path
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec app printenv UPLOAD_FOLDER

# Re-sync uploads manually
rsync -avz /tmp/migration/uploads/ data/uploads/

# Restart the stack to pick up any file system changes
docker compose --env-file .env.prod -f docker-compose.prod.yml restart app
```

---

### TOTP codes rejected on live server

**Symptom:** Admin enters a valid code from the authenticator app but login fails.

**Cause:** Server clock is out of sync (TOTP requires clocks within ±30 seconds).

**Resolution:**

```bash
# Check and sync server time (Ubuntu)
timedatectl status
sudo timedatectl set-ntp true
timedatectl status   # confirm "NTP service: active"
```

If the TOTP secret was set on beta and needs to be re-enrolled on live:

1. Use the database reset script in Phase 6.1 to clear `totp_secret` and `totp_enabled`.
2. Re-enroll via `/admin/setup_authenticator`.

---

### Rollback procedure

If the live server migration fails and the application needs to be reverted:

1. **Stop the live stack:**
   ```bash
   docker compose --env-file .env.prod -f docker-compose.prod.yml down
   ```

2. **Restore from the pre-restore safety copy** created automatically in Phase 4.4:
   ```bash
   ls data/secure_backups/clinic_pre_restore_*.db
   cp data/secure_backups/clinic_pre_restore_<TIMESTAMP>.db data/clinic.db
   ```

3. **Restart the stack:**
   ```bash
   docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
   ```

4. **Verify the rollback:**
   ```bash
   docker compose --env-file .env.prod -f docker-compose.prod.yml \
     exec app python3 -c "
   import sqlite3, os
   db = sqlite3.connect(os.environ.get('DATABASE', '/data/clinic.db'))
   print('Integrity:', db.execute('PRAGMA integrity_check').fetchone())
   "
   ```

5. Keep the beta server running until the root cause is identified and a new migration
   attempt is planned.

---

## Contact & Support

| Role | Contact |
|------|---------|
| System administrator | *(fill in)* |
| Application developer | *(fill in)* |
| Cloud/infrastructure | *(fill in)* |

For urgent issues outside business hours, use the on-call escalation path defined in your
organisation's runbook.
