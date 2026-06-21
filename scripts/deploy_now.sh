#!/usr/bin/env bash
# =============================================================================
# deploy_now.sh — One-shot AWS deployment helper
#
# Fill in the three required variables below, then run:
#   bash scripts/deploy_now.sh
# =============================================================================

# --- FILL THESE IN BEFORE RUNNING ---
SERVER_IP=""          # e.g. 13.61.60.244
SSH_KEY_PATH=""       # e.g. /home/lioraloni/private-clinic-key.pem
DOMAIN=""             # e.g. clinic.lior-clinic.org
# ------------------------------------

set -euo pipefail

if [[ -z "${SERVER_IP}" || -z "${SSH_KEY_PATH}" || -z "${DOMAIN}" ]]; then
  echo "ERROR: Please set SERVER_IP, SSH_KEY_PATH, and DOMAIN at the top of this script."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
if [[ "${CURRENT_BRANCH}" == "HEAD" || -z "${CURRENT_BRANCH}" ]]; then
  CURRENT_BRANCH="main"
fi

echo "[deploy_now] Using local branch: ${CURRENT_BRANCH}"
echo "[deploy_now] Using local commit: $(git rev-parse HEAD)"

echo "[deploy_now] Creating fresh encrypted backup..."
python3 scripts/backup_db.py

echo "[deploy_now] Running migration to AWS (${SERVER_IP})..."
bash scripts/migrate_to_aws.sh \
  --ssh-target "ubuntu@${SERVER_IP}" \
  --ssh-key "${SSH_KEY_PATH}" \
  --domain "${DOMAIN}" \
  --git-branch "${CURRENT_BRANCH}"

echo "[deploy_now] Uploading current local checkout to guarantee latest local code is deployed..."
bash scripts/deploy_local_bundle_to_aws.sh \
  --ssh-target "ubuntu@${SERVER_IP}" \
  --ssh-key "${SSH_KEY_PATH}"

echo "[deploy_now] Done. Visit https://${DOMAIN}/ to verify the deployment."
