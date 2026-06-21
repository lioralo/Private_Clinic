# Quick Start: Deploy to AWS

## Option 1: Automated Script (Recommended)

```bash
# Set your deployment variables
export SERVER_IP="13.61.60.244"
export SSH_KEY_PATH="/path/to/private-clinic-key.pem"
export DOMAIN="clinic.yourdomain.com"

# Run the deployment with verification
bash scripts/deploy_with_verify.sh
```

**What it does:**
✓ Verifies local git state
✓ Creates encrypted backup
✓ Migrates infrastructure to AWS
✓ Deploys your local code
✓ Verifies remote state
✓ Checks Docker services
✓ Reviews app logs
✓ Tests HTTPS endpoints

---

## Option 2: Copilot CLI (For step-by-step control)

1. Open Copilot CLI in repo root
2. Paste the prompt from `docs/DEPLOYMENT_GUIDE.md` section "Copilot CLI — Deployment Verification Prompt"
3. Replace the placeholders with your actual values:
   - `SERVER_IP`: Your AWS instance public IP
   - `SSH_KEY_PATH`: Path to your PEM key
   - `DOMAIN`: Your live domain

---

## Before You Deploy

- [ ] Verify repo is synced: `git status` (should say "up to date")
- [ ] Check .env.prod exists on server or will be created by migration script
- [ ] Verify SSH key is readable: `ls -l /path/to/key.pem` (should be `-rw-------`)
- [ ] AWS security group allows SSH (port 22) from your IP
- [ ] AWS security group allows HTTPS (ports 80, 443)

---

## Verify Deployment Success

After running either option above, confirm:

1. **Homepage loads:** `https://clinic.yourdomain.com/` → Status 200
2. **Admin portal exists:** `https://clinic.yourdomain.com/admin/` → Status 200
3. **CRM interface works:** `https://clinic.yourdomain.com/crm` → Status 200
4. **Containers running:** `ssh -i key.pem ubuntu@IP "docker compose ps"`
5. **No errors in logs:** `ssh -i key.pem ubuntu@IP "docker compose logs app" | grep -i error`

---

## Rollback (if needed)

If the deployment has issues:

```bash
# SSH into the server
ssh -i /path/to/key.pem ubuntu@13.61.60.244

# Stop containers
cd /opt/Private_Clinic
sudo docker compose down

# Restore from previous backup
python3 scripts/restore_db.py secure_backups/clinic_PREVIOUS.db.enc

# Start containers again
sudo docker compose up -d
```

---

## Need Help?

- See `docs/DEPLOYMENT_GUIDE.md` for detailed troubleshooting
- Check deploy script source: `cat scripts/deploy_with_verify.sh`
- Review AWS instance logs: `sudo journalctl -xe`

