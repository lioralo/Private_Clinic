# Copilot CLI — Deployment Verification Prompt

Use this prompt in the GitHub Copilot CLI from the repo root to perform a complete deployment flow verification.

## How to Use

From the repo root directory, paste this into Copilot CLI:

```
You are managing a deployment of the Private_Clinic repo to AWS. 

My local checkout is synced to the latest. I need you to verify and complete the deployment flow step-by-step. Show output after each step.

Environment variables (replace with your actual values):
- SERVER_IP: 13.61.60.244
- SSH_KEY_PATH: /home/lioraloni/private-clinic-key.pem
- DOMAIN: clinic.yourdomain.com

Do exactly these steps in order:

1. Print local git branch and commit hash
   Command: git rev-parse --abbrev-ref HEAD && git rev-parse HEAD

2. Verify git working directory is clean
   Command: git status --short

3. Create encrypted database backup
   Command: python3 scripts/backup_db.py
   
4. Run AWS migration (clones/updates repo on server, restores DB, starts services)
   Command: bash scripts/migrate_to_aws.sh --ssh-target ubuntu@13.61.60.244 --ssh-key /home/lioraloni/private-clinic-key.pem --domain clinic.yourdomain.com

5. Deploy local bundle to AWS (uploads current checkout state to server)
   Command: bash scripts/deploy_local_bundle_to_aws.sh --ssh-target ubuntu@13.61.60.244 --ssh-key /home/lioraloni/private-clinic-key.pem

6. Verify remote git state
   Command: ssh -i /home/lioraloni/private-clinic-key.pem -o StrictHostKeyChecking=accept-new ubuntu@13.61.60.244 "cd /opt/Private_Clinic && git rev-parse HEAD"

7. Check Docker services on remote
   Command: ssh -i /home/lioraloni/private-clinic-key.pem -o StrictHostKeyChecking=accept-new ubuntu@13.61.60.244 "cd /opt/Private_Clinic && sudo docker compose --env-file .env.prod -f docker-compose.prod.yml ps"

8. Get recent application logs (last 80 lines from app and caddy)
   Command: ssh -i /home/lioraloni/private-clinic-key.pem -o StrictHostKeyChecking=accept-new ubuntu@13.61.60.244 "cd /opt/Private_Clinic && sudo docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=80 app caddy"

9. Test HTTPS endpoints (root, admin, crm)
   Commands:
   - curl -s -o /dev/null -w "Homepage: %{http_code}\n" https://clinic.yourdomain.com/
   - curl -s -o /dev/null -w "Admin: %{http_code}\n" https://clinic.yourdomain.com/admin/
   - curl -s -o /dev/null -w "CRM: %{http_code}\n" https://clinic.yourdomain.com/crm

If any step fails:
- Stop immediately
- Show the exact failing command and its error output
- Explain the exact fix needed
- Do NOT attempt to recover automatically
```

## Alternative: Unified Script

If you prefer a single command, use the local script instead:

```bash
SERVER_IP=13.61.60.244 \
SSH_KEY_PATH=/home/lioraloni/private-clinic-key.pem \
DOMAIN=clinic.yourdomain.com \
bash deploy_with_verify.sh
```

This runs all 8 steps with colored output and better error handling.

## What Each Step Does

| Step | Purpose | Failure Impact |
|------|---------|-----------------|
| 1-2 | Verify local state is clean | Warns if uncommitted changes present |
| 3 | Backup encrypted database | Prevents data loss if restore fails |
| 4 | Setup and migrate AWS infrastructure | No app runs without this |
| 5 | Deploy current local code | Remote doesn't have your latest changes |
| 6 | Verify remote commit matches | Detects if deployment didn't complete |
| 7 | Check containers are running | Detects crashed services |
| 8 | Review app logs for errors | Catches startup errors early |
| 9 | Test public HTTPS endpoints | Verifies reverse proxy and SSL are working |

## Troubleshooting

### SSH Connection Fails
- Verify SERVER_IP is correct and AWS security group allows SSH (port 22)
- Check SSH_KEY_PATH exists and has correct permissions: `chmod 600 /path/to/key.pem`
- Try manually: `ssh -i /path/to/key.pem ubuntu@13.61.60.244`

### Docker Services Not Running
- SSH to server: `ssh -i /path/to/key.pem ubuntu@13.61.60.244`
- Check logs: `cd /opt/Private_Clinic && sudo docker compose logs -f`
- Restart: `sudo docker compose restart`

### HTTPS Returns 404 or 502
- DNS not resolving: `nslookup clinic.yourdomain.com`
- Caddy reverse proxy not routing: Check `/opt/Private_Clinic/Caddyfile`
- App container crashed: `sudo docker compose ps` and `sudo docker compose logs app`

### Database Restore Failed
- Check backup file exists: `ls -lh /opt/Private_Clinic/secure_backups/`
- Check backup key is in .env.prod: `grep BACKUP_ENCRYPTION_KEY .env.prod`
- Manual restore: `python3 scripts/restore_db.py secure_backups/clinic_*.db.enc`
