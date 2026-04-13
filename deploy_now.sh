#!/usr/bin/env bash
# =============================================================================
# deploy_now.sh — One-shot AWS deployment helper
#
# Fill in the three required variables below, then run:
#   bash deploy_now.sh
# =============================================================================

# --- FILL THESE IN BEFORE RUNNING ---
SERVER_IP=""          # e.g. 3.14.15.92
SSH_KEY_PATH=""       # e.g. /home/lioraloni/private-clinic-key.pem
DOMAIN=""             # e.g. clinic.yourdomain.com
# ------------------------------------

set -euo pipefail

if [[ -z "${SERVER_IP}" || -z "${SSH_KEY_PATH}" || -z "${DOMAIN}" ]]; then
  echo "ERROR: Please set SERVER_IP, SSH_KEY_PATH, and DOMAIN at the top of this script."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "[deploy_now] Creating fresh encrypted backup..."
python3 backup_db.py

echo "[deploy_now] Running migration to AWS (${SERVER_IP})..."
bash scripts/migrate_to_aws.sh \
  --ssh-target "ubuntu@${SERVER_IP}" \
  --ssh-key "${SSH_KEY_PATH}" \
  --domain "${DOMAIN}"

echo "[deploy_now] Done. Visit https://${DOMAIN}/ to verify the deployment."
