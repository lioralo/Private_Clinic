# Live Deployment Guide (Docker + HTTPS)

This guide publishes the clinic as a live website with:
- Flask app served by Gunicorn
- Caddy reverse proxy with automatic TLS certificates
- Persistent storage for DB, uploads, patient logs, and encrypted backups

## 1. Prepare a Server

Use an Ubuntu 24.04 VPS with a public IP.

### AWS EC2 Quick Path

If you are deploying on AWS, use these values when launching the instance:

- Region: `il-central-1` (Israel / Tel Aviv)
- AMI: `Ubuntu Server 24.04 LTS`
- Instance type: `t3.micro`
- Storage: `20 GiB gp3`
- Inbound ports: `22`, `80`, `443`

SSH into the server with:

```bash
chmod 400 /path/to/private-clinic-key.pem
ssh -i /path/to/private-clinic-key.pem ubuntu@<server-ip>
```

If you want the server IP to remain stable, allocate and associate an Elastic IP before pointing DNS.

Install Docker with the commands below. If you already have a local checkout of the repo on the server, you can also run `bash scripts/setup_ubuntu_docker.sh`.

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
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
bash scripts/deploy_prod.sh
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

## 9. First-Time AWS Operator Checklist

Use this exact order on a fresh EC2 server:

1. Connect over SSH as `ubuntu`.
2. Run the setup helper or the manual Docker install commands.
3. Clone the repo and enter it:

   ```bash
   git clone https://github.com/lioralo/Private_Clinic.git
   cd Private_Clinic
   ```

4. Copy the production env file:

   ```bash
   cp .env.prod.example .env.prod
   ```

5. Generate secure values:

   ```bash
   python3 - <<'PY'
   import secrets
   from cryptography.fernet import Fernet
   print('SECRET_KEY=' + secrets.token_urlsafe(64))
   print('BACKUP_ENCRYPTION_KEY=' + Fernet.generate_key().decode())
   PY
   ```

6. Edit `.env.prod` and set:
   - `DOMAIN` to your live domain
   - `SECRET_KEY` to the generated secret
   - `BACKUP_ENCRYPTION_KEY` to the generated Fernet key

7. Start the stack:

   ```bash
   bash scripts/deploy_prod.sh
   ```

8. Verify:

   ```bash
   sudo docker compose --env-file .env.prod -f docker-compose.prod.yml ps
   sudo docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f
   ```

## 10. Automated Migration From Local Data To AWS

If your source data already exists locally in this checkout (`clinic.db`,
`secure_backups/clinic_*.db.enc`, `static/uploads`, `patients_logs`,
`app_log.txt`), you can automate the AWS migration from the operator
workstation:

```bash
python3 backup_db.py
bash scripts/migrate_to_aws.sh \
  --ssh-target ubuntu@<server-ip> \
  --ssh-key /path/to/private-clinic-key.pem \
  --domain clinic.yourdomain.com
```

The helper will:
- upload the encrypted backup and supplementary artifacts
- clone or update the repo on the AWS host
- write `.env.prod` with the live `DOMAIN`, a generated `SECRET_KEY`, and the
  local backup encryption key
- start the production stack and restore the encrypted backup
- print post-restore integrity and row-count checks for `patients`,
  `appointments`, and `users`
