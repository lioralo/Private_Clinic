# Private Clinic — Beta → Live Migration Guide

This document provides a step-by-step guide to migrate the Private Clinic
application from a **beta server** to a **live production server**.
Follow every phase in order and do not skip validation steps.

---

## Prerequisites

| Item | Requirement |
|------|-------------|
| Beta server | SSH access, Docker running, app healthy |
| Live server | Ubuntu 24.04, Docker installed, ports 22/80/443 open |
| Operator workstation | `scp`/`ssh` available, Python 3 installed |
| DNS | `A` record for the live domain already pointing to the live server IP |
| Downtime window | Allow ≥ 30 minutes of planned downtime |

> **Security note** – Never transmit encryption keys or `.env` files over
> unencrypted channels. All transfers in this guide use SSH/SCP.

---

## Phase 1 — Pre-Migration Checklist

Run these checks **on the beta server** before you begin.

### 1.1 Verify the backup encryption key is set

```bash
# On beta server
grep BACKUP_ENCRYPTION_KEY /opt/Private_Clinic/.env.prod
```

If the variable is empty, the app will have used a key stored in
`./data/secure_backups/.backup.key`. Confirm the key file exists:

```bash
ls -la /opt/Private_Clinic/data/secure_backups/.backup.key
```

Record which key source is active — you will need it in Phase 3.

### 1.2 Verify admin credentials are known

Log in to the beta app (`https://<beta-domain>/login`) with the admin account
and confirm access works.  If TOTP is enabled, have the authenticator app
ready.

### 1.3 Check database integrity

```bash
# On beta server — inside or outside the container
sqlite3 /opt/Private_Clinic/data/clinic.db "PRAGMA integrity_check;"
```

Expected output: `ok`

If the result is anything other than `ok`, **stop** and investigate before
continuing.

### 1.4 Validate network connectivity to the live server

```bash
# On operator workstation
ssh -i /path/to/live-key.pem ubuntu@<live-server-ip> echo "Live server reachable"
```

---

## Phase 2 — Beta Server Extraction

### 2.1 Create a fresh encrypted backup via the app

Log in to the beta app as admin and use the **Admin → Backup** button to
trigger a new encrypted backup, **or** run the backup script directly:

```bash
# On beta server
cd /opt/Private_Clinic
docker compose --env-file .env.prod -f docker-compose.prod.yml exec app \
    python backup_db.py
```

The new backup file will appear in `./data/secure_backups/` with a name like
`clinic_YYYYMMDD_HHMMSS.db.enc`.

### 2.2 Note the backup filename

```bash
# On beta server
ls -lht /opt/Private_Clinic/data/secure_backups/clinic_*.db.enc | head -5
```

Copy the full filename of the newest `.enc` file — you will reference it in
Phase 3.

### 2.3 Verify backup integrity (decrypt test)

```bash
# On beta server — quick smoke-test
docker compose --env-file .env.prod -f docker-compose.prod.yml exec app \
    python3 - <<'PY'
import os
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet

backup_dir = Path("/data/secure_backups")
enc_file = sorted(backup_dir.glob("clinic_*.db.enc"))[-1]
key = os.environ["BACKUP_ENCRYPTION_KEY"].encode()
decrypted = Fernet(key).decrypt(enc_file.read_bytes())
assert decrypted[:16] == b"SQLite format 3\x00", "SQLite header missing!"
print(f"Integrity OK: {enc_file.name}")
PY
```

### 2.4 Collect the encryption key

**Option A — key is stored in `.env.prod`:**

```bash
grep BACKUP_ENCRYPTION_KEY /opt/Private_Clinic/.env.prod
# e.g.  BACKUP_ENCRYPTION_KEY=abc123...==
```

**Option B — key is stored in the key file:**

```bash
cat /opt/Private_Clinic/data/secure_backups/.backup.key
```

Store the key value in a temporary local file on your **operator workstation**
(not on any server):

```bash
echo "BACKUP_ENCRYPTION_KEY=<paste-key-here>" > /tmp/migration_key.env
chmod 600 /tmp/migration_key.env
```

### 2.5 Document artifact sizes

```bash
# On beta server
du -sh \
    /opt/Private_Clinic/data/clinic.db \
    /opt/Private_Clinic/data/uploads \
    /opt/Private_Clinic/data/patients_logs \
    /opt/Private_Clinic/data/app_log.txt \
    /opt/Private_Clinic/data/secure_backups
```

Record the sizes for post-migration verification.

---

## Phase 3 — Data Transfer

All transfers run **from the operator workstation**.

### 3.1 Create a staging directory on the live server

```bash
ssh -i /path/to/live-key.pem ubuntu@<live-server-ip> \
    "mkdir -p ~/migration_staging"
```

### 3.2 Transfer the encrypted backup file

```bash
BACKUP_FILE="clinic_YYYYMMDD_HHMMSS.db.enc"   # ← replace with actual filename

scp -i /path/to/live-key.pem \
    ubuntu@<beta-server-ip>:/opt/Private_Clinic/data/secure_backups/${BACKUP_FILE} \
    ubuntu@<live-server-ip>:~/migration_staging/${BACKUP_FILE}
```

> If you cannot SCP between servers directly, download to the workstation
> first and then upload to the live server.

### 3.3 Transfer the encryption key

```bash
# Transfer the key file OR set it via env — never leave it in plain text on disk
scp -i /path/to/live-key.pem \
    /tmp/migration_key.env \
    ubuntu@<live-server-ip>:~/migration_staging/migration_key.env

# Tighten permissions immediately
ssh -i /path/to/live-key.pem ubuntu@<live-server-ip> \
    "chmod 600 ~/migration_staging/migration_key.env"
```

### 3.4 Transfer supplementary artifacts (uploads, logs)

```bash
# Uploads
rsync -az -e "ssh -i /path/to/beta-key.pem" \
    ubuntu@<beta-server-ip>:/opt/Private_Clinic/data/uploads/ \
    /tmp/migration_uploads/

rsync -az -e "ssh -i /path/to/live-key.pem" \
    /tmp/migration_uploads/ \
    ubuntu@<live-server-ip>:~/migration_staging/uploads/

# Patient logs
rsync -az -e "ssh -i /path/to/beta-key.pem" \
    ubuntu@<beta-server-ip>:/opt/Private_Clinic/data/patients_logs/ \
    /tmp/migration_patients_logs/

rsync -az -e "ssh -i /path/to/live-key.pem" \
    /tmp/migration_patients_logs/ \
    ubuntu@<live-server-ip>:~/migration_staging/patients_logs/

# App log (optional — carry history)
scp -i /path/to/beta-key.pem \
    ubuntu@<beta-server-ip>:/opt/Private_Clinic/data/app_log.txt \
    /tmp/migration_app_log.txt

scp -i /path/to/live-key.pem \
    /tmp/migration_app_log.txt \
    ubuntu@<live-server-ip>:~/migration_staging/app_log.txt
```

### 3.5 Verify transferred files on the live server

```bash
ssh -i /path/to/live-key.pem ubuntu@<live-server-ip> \
    "ls -lh ~/migration_staging/ && du -sh ~/migration_staging/*"
```

Confirm the `.db.enc` file size matches what you recorded in Phase 2.5.

---

## Phase 4 — Live Server Restoration

All commands in this phase run **on the live server** unless noted.

### 4.1 Deploy the application (if not already running)

```bash
# On live server
cd /opt/Private_Clinic    # or wherever the repo lives
git clone https://github.com/lioralo/Private_Clinic.git .  # skip if already cloned

cp .env.prod.example .env.prod
```

Set the **same** `BACKUP_ENCRYPTION_KEY` value that was used on the beta
server (from `~/migration_staging/migration_key.env`):

```bash
source ~/migration_staging/migration_key.env   # loads BACKUP_ENCRYPTION_KEY
# Then edit .env.prod manually and set DOMAIN and SECRET_KEY as well
nano .env.prod
```

Minimum required values in `.env.prod`:

```
DOMAIN=clinic.yourdomain.com
SECRET_KEY=<long-random-value>
BACKUP_ENCRYPTION_KEY=<same-key-as-beta>
```

Generate a new `SECRET_KEY` if one does not exist:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

### 4.2 Stop any running containers

```bash
# On live server
cd /opt/Private_Clinic
docker compose --env-file .env.prod -f docker-compose.prod.yml down
```

### 4.3 Place the backup file into the data directory

```bash
# On live server
mkdir -p /opt/Private_Clinic/data/secure_backups

BACKUP_FILE="clinic_YYYYMMDD_HHMMSS.db.enc"   # ← replace with actual filename

cp ~/migration_staging/${BACKUP_FILE} \
   /opt/Private_Clinic/data/secure_backups/${BACKUP_FILE}
```

### 4.4 Restore supplementary artifacts

```bash
# On live server
mkdir -p /opt/Private_Clinic/data/uploads
mkdir -p /opt/Private_Clinic/data/patients_logs

rsync -a ~/migration_staging/uploads/    /opt/Private_Clinic/data/uploads/
rsync -a ~/migration_staging/patients_logs/ /opt/Private_Clinic/data/patients_logs/

# App log (append if file already exists, copy if it doesn't)
if [ -f /opt/Private_Clinic/data/app_log.txt ]; then
    cat ~/migration_staging/app_log.txt >> /opt/Private_Clinic/data/app_log.txt
else
    cp ~/migration_staging/app_log.txt /opt/Private_Clinic/data/app_log.txt
fi
```

### 4.5 Start the stack

```bash
# On live server
cd /opt/Private_Clinic
bash scripts/deploy_prod.sh
```

### 4.6 Restore the database from backup via the app

Once the containers are running, trigger a restore through the admin UI:

1. Open `https://<live-domain>/admin` and log in.
2. Navigate to **Admin → Restore Backup**.
3. Select the backup file `clinic_YYYYMMDD_HHMMSS.db.enc`.
4. Confirm the restore.

**Alternatively**, restore via the container shell:

```bash
# On live server
docker compose --env-file .env.prod -f docker-compose.prod.yml exec app \
    python3 - <<'PY'
import os
from app import app, perform_encrypted_restore

BACKUP_FILE = "clinic_YYYYMMDD_HHMMSS.db.enc"   # ← replace

with app.app_context():
    target, safety = perform_encrypted_restore("/data/clinic.db", BACKUP_FILE)
    print(f"Restored from: {target}")
    print(f"Safety copy at: {safety}")
PY
```

### 4.7 Post-restore integrity check

```bash
# On live server
sqlite3 /opt/Private_Clinic/data/clinic.db "PRAGMA integrity_check;"
```

Expected: `ok`

Also check row counts match what you recorded in Phase 2.5:

```bash
sqlite3 /opt/Private_Clinic/data/clinic.db \
    "SELECT 'patients', COUNT(*) FROM patients
     UNION ALL SELECT 'appointments', COUNT(*) FROM appointments
     UNION ALL SELECT 'users', COUNT(*) FROM users;"
```

---

## Phase 5 — Post-Migration Validation

### 5.1 Application health check

```bash
# On operator workstation
curl -s -o /dev/null -w "%{http_code}" https://<live-domain>/
# Expected: 200 or 302
```

### 5.2 Admin login test

Open `https://<live-domain>/login` in a browser and log in with the admin
account.  If TOTP is enabled see Phase 6.2.

### 5.3 Data completeness verification

In the admin UI verify:
- Patient list shows the expected number of records.
- Appointment calendar shows existing appointments.
- Uploaded files/attachments are accessible.

### 5.4 Log integrity

```bash
# On live server
tail -50 /opt/Private_Clinic/data/app_log.txt
```

Confirm log entries from the beta server are present and there are no
unexpected error lines following the restore.

### 5.5 Container health

```bash
# On live server
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=50
```

All services should show state `running` (or `Up`).

---

## Phase 6 — Operational Handoff

### 6.1 Reset admin password on the live server

Immediately change the admin password after migration:

1. Log in to the live app as admin.
2. Navigate to **Admin → Profile**.
3. Set a new strong password (the application enforces a minimum of 5 characters; use a strong passphrase of ≥ 16 characters in practice).

### 6.2 TOTP authenticator setup

If the admin account uses TOTP (time-based one-time passwords):

1. In **Admin → Profile**, disable the existing TOTP device.
2. Re-enroll the authenticator app by scanning the new QR code.
3. Verify login with the new TOTP code before logging out.

### 6.3 Access control verification

```bash
# Confirm non-admin routes redirect unauthenticated users
curl -s -o /dev/null -w "%{http_code}" https://<live-domain>/admin/
# Expected: 302 (redirect to login)

curl -s -o /dev/null -w "%{http_code}" https://<live-domain>/crm
# Expected: 302 (redirect to login)
```

### 6.4 Scheduled backups & monitoring

Ensure automated backups are scheduled on the live server:

```bash
# Add a daily cron job (example — adjust path/time as needed)
(crontab -l 2>/dev/null; echo "0 2 * * * cd /opt/Private_Clinic && \
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T app \
python backup_db.py >> /var/log/clinic_backup.log 2>&1") | crontab -
```

Verify the cron entry:

```bash
crontab -l
```

Set up basic uptime monitoring (e.g. UptimeRobot free tier) pointing to
`https://<live-domain>/` to receive alerts on downtime.

### 6.5 Clean up migration staging files

```bash
# On live server — remove sensitive key material
rm -rf ~/migration_staging/

# On operator workstation
rm -f /tmp/migration_key.env /tmp/migration_app_log.txt
rm -rf /tmp/migration_uploads/ /tmp/migration_patients_logs/
```

---

## Troubleshooting

### Backup decryption fails (`InvalidToken`)

**Symptom:** `cryptography.fernet.InvalidToken` during restore.

**Cause:** The `BACKUP_ENCRYPTION_KEY` in `.env.prod` on the live server does
not match the key used to create the backup on the beta server.

**Fix:**
1. Retrieve the correct key from the beta server (Phase 2.4).
2. Update `BACKUP_ENCRYPTION_KEY` in `/opt/Private_Clinic/.env.prod`.
3. Restart the stack: `docker compose ... restart app`.
4. Retry the restore.

### Database integrity check fails after restore

**Symptom:** `PRAGMA integrity_check` returns something other than `ok`.

**Fix:**
1. The restore created a safety copy under
   `./data/secure_backups/clinic_pre_restore_<timestamp>/`.
2. Identify the most recent safety copy:
   ```bash
   ls -lht /opt/Private_Clinic/data/secure_backups/clinic_pre_restore_*/
   ```
3. Roll back to it:
   ```bash
   cp /opt/Private_Clinic/data/secure_backups/clinic_pre_restore_<timestamp>/clinic.db \
      /opt/Private_Clinic/data/clinic.db
   ```
4. Restart the app container.

### Container fails to start (port conflict)

**Symptom:** `Bind for 0.0.0.0:80 failed: port is already allocated`.

**Fix:**
```bash
# Find the conflicting process
sudo ss -tlnp | grep ':80'
sudo ss -tlnp | grep ':443'

# Stop it (example — nginx)
sudo systemctl stop nginx
sudo systemctl disable nginx

# Then retry
bash scripts/deploy_prod.sh
```

### HTTPS certificate not issued by Caddy

**Symptom:** Browser shows `NET::ERR_CERT_INVALID` or Caddy logs show
`no such host` / ACME errors.

**Fix:**
1. Confirm DNS propagation: `dig +short <live-domain>` must return the
   live server IP.
2. Ensure ports 80 and 443 are reachable from the internet (check security
   group / firewall rules).
3. Check Caddy logs:
   ```bash
   docker compose --env-file .env.prod -f docker-compose.prod.yml logs caddy
   ```
4. If using `DOMAIN=localhost` or an internal hostname, TLS will not work.
   Set the real public domain in `.env.prod`.

### Admin login fails after migration

**Symptom:** Correct credentials rejected on the live server.

**Cause:** The restored database may be from an older backup that does not
include recent password changes, **or** the session cookie secret changed.

**Fix:**
1. Verify the database was restored correctly (Phase 4.7 row counts).
2. Use the most recent backup file.
3. If locked out, reset the admin password via the container shell:
   ```bash
   docker compose --env-file .env.prod -f docker-compose.prod.yml exec app \
       python3 - <<'PY'
   from app import app
   from app import get_db
   from werkzeug.security import generate_password_hash

   NEW_PASSWORD = "ChangeMe_Immediately_123!"

   with app.app_context():
       db = get_db()
       db.execute(
           "UPDATE users SET password_hash = ? WHERE role = 'admin'",
           (generate_password_hash(NEW_PASSWORD),)
       )
       db.commit()
       print("Admin password reset.")
   PY
   ```
   Log in with the temporary password and change it immediately in the UI.

---

## Rollback Procedure

If migration must be aborted **after** the live restore has run:

1. **Stop live containers:**
   ```bash
   docker compose --env-file .env.prod -f docker-compose.prod.yml down
   ```
2. **Restore the pre-restore safety copy** (created automatically during restore):
   ```bash
   SAFETY="clinic_pre_restore_<timestamp>"
   cp /opt/Private_Clinic/data/secure_backups/${SAFETY}/clinic.db \
      /opt/Private_Clinic/data/clinic.db
   ```
3. **Restore artifact safety copies** (in the same `${SAFETY}` directory):
   ```bash
   rsync -a /opt/Private_Clinic/data/secure_backups/${SAFETY}/uploads/ \
             /opt/Private_Clinic/data/uploads/
   rsync -a /opt/Private_Clinic/data/secure_backups/${SAFETY}/patients_logs/ \
             /opt/Private_Clinic/data/patients_logs/
   ```
4. **Restart:**
   ```bash
   bash scripts/deploy_prod.sh
   ```
5. **Verify** using the checks in Phase 5.

---

## Support Contact

If you encounter an issue not covered by this guide, contact the system
administrator with:
- The exact error message from the logs (`docker compose ... logs --tail=100`)
- The output of `PRAGMA integrity_check` on the database
- The backup filename used for the restore
- The timestamp at which the failure occurred
