# Deployment Instructions

## Required Files

These must exist on the local machine (paths from this session):

| File | Path |
|------|------|
| SSH Key | `/home/lioraloni/Documents/private-clinic-key.pem` |
| SES Credentials | `/home/lioraloni/Documents/lior_credentials.csv` |
| Google OAuth | `/home/lioraloni/Documents/client_secret_168436965515-qbi7fh1ns3f1f8omjlgdvp1pdc7uc8pk.apps.googleusercontent.com.json` |

## Server Connection

```
Server IP:  13.61.60.244
SSH User:   ubuntu
SSH Key:    /home/lioraloni/Documents/private-clinic-key.pem
Repo:       https://github.com/lioralo/Private_Clinic.git
Repo Dir:   /home/ubuntu/clinic
```

## Deployment Commands

Run these in order:

```bash
# 1. SSH into the server
ssh -i /home/lioraloni/Documents/private-clinic-key.pem -o StrictHostKeyChecking=no ubuntu@13.61.60.244

# 2. Pull latest code
cd /home/ubuntu/clinic && git pull

# 3. Build the Docker image (--no-cache forces fresh COPY of templates)
docker compose -f docker-compose.prod.yml build --no-cache app

# 4. Stop and remove the old container
docker rm -f private_clinic_app

# 5. Start the new container
docker compose -f docker-compose.prod.yml up -d app

# 6. Wait for health check, then reconnect Caddy to the app's network
sleep 5
docker network connect clinic_default private_clinic_caddy 2>/dev/null

# 7. Verify
curl -sk -o /dev/null -w '%{http_code}\n' https://clinic.lior-clinic.org/healthz
# Should output: 200
```

## One-liner for Remote Deploy

From your local machine:

```bash
ssh -i /home/lioraloni/Documents/private-clinic-key.pem -o StrictHostKeyChecking=no ubuntu@13.61.60.244 \
  'cd /home/ubuntu/clinic && git pull && \
   docker compose -f docker-compose.prod.yml build --no-cache app && \
   docker rm -f private_clinic_app && \
   docker compose -f docker-compose.prod.yml up -d app && \
   sleep 5 && \
   docker network connect clinic_default private_clinic_caddy 2>/dev/null; \
   curl -sk -o /dev/null -w "HTTPS: %{http_code}\n" https://clinic.lior-clinic.org/healthz'
```

## Important Notes

- **Never run `docker compose down -v`** — destroys the data volume. All data (database, uploads, backups) lives in the named volume `private_clinic_clinic_app_data`.
- **The `--no-cache` flag is required** — Docker caches the `COPY . .` layer and won't pick up new template/code changes without it.
- **Step 6 (network connect) fixes a known issue** — the Caddy container was started from a different compose project and is on a different Docker network than the app. The reconnect is needed after every app restart.
- **The `.env` file on the server** (at `/home/ubuntu/clinic/.env`) contains secrets — it should never be committed to git.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Calendar shows blank | `docker exec private_clinic_app grep -c "fillVacancyFormForEdit" /app/templates/calendar.html` — should be `2` |
| HTTPS returns 502 | Caddy network issue — rerun: `docker network connect clinic_default private_clinic_caddy` |
| Data appears lost | Volume mismatch — verify: `docker inspect private_clinic_app --format '{{json .Mounts}}' | python3 -m json.tool` should show `private_clinic_clinic_app_data` |
| App won't start | `docker logs private_clinic_app --tail 50` |
| CSS is stale | Rebuild Tailwind locally before deploy: `cd /home/lioraloni/Private_Clinic && npx tailwindcss -i static/css/input.css -o static/css/tailwind.css && git add static/css/tailwind.css && git commit -m "rebuild tailwind" && git push` |
