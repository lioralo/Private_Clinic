# Live Deployment Guide (Docker + HTTPS)

This guide publishes the clinic as a live website with:
- Flask app served by Gunicorn
- Caddy reverse proxy with automatic TLS certificates
- Persistent storage for DB, uploads, patient logs, and encrypted backups

## 1. Prepare a Server

Use an Ubuntu 24.04 VPS with a public IP.

Install Docker:

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

## 2. Point Domain DNS

Create an `A` record so your domain points to your server IP.

Example:
- `clinic.yourdomain.com -> <server-ip>`

## 3. Upload Project To Server

```bash
git clone https://github.com/lioralo/Private_Clinic.git
cd Private_Clinic
```

## 4. Configure Production Environment

Copy and edit env file:

```bash
cp .env.prod.example .env.prod
```

Set these values in `.env.prod`:
- `DOMAIN`: your live domain
- `SECRET_KEY`: long random value
- `BACKUP_ENCRYPTION_KEY`: Fernet key (base64)

Generate secure values:

```bash
python3 - <<'PY'
import secrets
from cryptography.fernet import Fernet
print('SECRET_KEY=' + secrets.token_urlsafe(64))
print('BACKUP_ENCRYPTION_KEY=' + Fernet.generate_key().decode())
PY
```

## 5. Start The Live Stack

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Check status:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f
```

## 6. What Is Persisted

All runtime clinic data is stored under `./data` on the server:
- `clinic.db`
- uploads (`/data/uploads`)
- patient logs (`/data/patients_logs`)
- app log (`/data/app_log.txt`)
- encrypted backups (`/data/secure_backups`)

This matches backup/restore behavior in the app.

## 7. Day-2 Operations

Update app:

```bash
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Restart services:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml restart
```

Stop services:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down
```

## 8. Security Checklist

- Change default admin credentials immediately.
- Keep `.env.prod` private.
- Restrict SSH access and use key auth.
- Enable server firewall (`ufw`) with only `22`, `80`, `443` open.
- Snapshot `./data` periodically at infrastructure level too.
