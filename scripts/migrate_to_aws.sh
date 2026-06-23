#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/migrate_to_aws.sh --ssh-target ubuntu@<server-ip> --domain clinic.example.com [options]

Required:
  --ssh-target TARGET      SSH target for the AWS host, e.g. ubuntu@1.2.3.4
  --domain DOMAIN          Live HTTPS domain for the deployment

Optional:
  --ssh-key PATH           PEM/private key path for SSH/SCP
  --remote-dir PATH        Remote repo path (default: /opt/Private_Clinic)
  --repo-url URL           Repo clone URL (default: https://github.com/lioralo/Private_Clinic.git)
  --git-branch NAME        Branch to deploy on the remote host (default: main)
  --secret-key VALUE       SECRET_KEY for .env.prod (default: generated locally)
  --backup-file PATH       Encrypted backup to migrate (default: latest secure_backups/clinic_*.db.enc)
  --skip-docker-setup      Skip Docker installation on the remote host
  --skip-healthcheck       Skip final HTTPS curl checks
  --dry-run                Print actions without executing them

This script:
  - stages a fresh encrypted backup and local runtime artifacts
  - clones or updates the app on the AWS host
  - writes .env.prod with DOMAIN, SECRET_KEY, and BACKUP_ENCRYPTION_KEY
  - starts the production stack
  - restores the encrypted backup on the AWS host
  - validates DB integrity and key row counts
EOF
}

log() {
  echo "[migrate_to_aws] $*"
}

die() {
  echo "[migrate_to_aws] ERROR: $*" >&2
  exit 1
}

quote_cmd() {
  local quoted=()
  for arg in "$@"; do
    quoted+=("$(printf '%q' "$arg")")
  done
  printf '%s\n' "${quoted[*]}"
}

run_cmd() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    quote_cmd "$@"
    return 0
  fi
  "$@"
}

run_ssh_script() {
  local script_content="$1"
  if [[ "${DRY_RUN}" == "1" ]]; then
    quote_cmd "${SSH_CMD[@]}" "bash -se"
    printf '%s\n' "${script_content}"
    return 0
  fi
  printf '%s\n' "${script_content}" | "${SSH_CMD[@]}" "bash -se"
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DIR="/opt/Private_Clinic"
REPO_URL="https://github.com/lioralo/Private_Clinic.git"
GIT_BRANCH="main"
SSH_TARGET=""
SSH_KEY=""
DOMAIN=""
SECRET_KEY=""
BACKUP_FILE=""
SKIP_DOCKER_SETUP=0
SKIP_HEALTHCHECK=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssh-target)
      SSH_TARGET="${2:-}"
      shift 2
      ;;
    --ssh-key)
      SSH_KEY="${2:-}"
      shift 2
      ;;
    --domain)
      DOMAIN="${2:-}"
      shift 2
      ;;
    --remote-dir)
      REMOTE_DIR="${2:-}"
      shift 2
      ;;
    --repo-url)
      REPO_URL="${2:-}"
      shift 2
      ;;
    --git-branch)
      GIT_BRANCH="${2:-}"
      shift 2
      ;;
    --secret-key)
      SECRET_KEY="${2:-}"
      shift 2
      ;;
    --backup-file)
      BACKUP_FILE="${2:-}"
      shift 2
      ;;
    --skip-docker-setup)
      SKIP_DOCKER_SETUP=1
      shift
      ;;
    --skip-healthcheck)
      SKIP_HEALTHCHECK=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[[ -n "${SSH_TARGET}" ]] || die "--ssh-target is required"
[[ -n "${DOMAIN}" ]] || die "--domain is required"

if [[ -n "${SSH_KEY}" && ! -f "${SSH_KEY}" ]]; then
  die "SSH key not found: ${SSH_KEY}"
fi

APP_LOG_FILE="${ROOT_DIR}/app_log.txt"
UPLOADS_DIR="${ROOT_DIR}/static/uploads"
PATIENT_LOGS_DIR="${ROOT_DIR}/patients_logs"
KEY_FILE="${ROOT_DIR}/secure_backups/.backup.key"
DB_FILE="${ROOT_DIR}/clinic.db"

if [[ -z "${BACKUP_FILE}" ]]; then
  BACKUP_FILE="$(cd "${ROOT_DIR}" && ls -1t secure_backups/clinic_*.db.enc 2>/dev/null | head -1 || true)"
  [[ -n "${BACKUP_FILE}" ]] || die "No encrypted backup found under secure_backups/"
  BACKUP_FILE="${ROOT_DIR}/${BACKUP_FILE}"
fi

[[ -f "${BACKUP_FILE}" ]] || die "Backup file not found: ${BACKUP_FILE}"
[[ -f "${DB_FILE}" ]] || die "Database file not found: ${DB_FILE}"
[[ -d "${UPLOADS_DIR}" ]] || die "Uploads directory not found: ${UPLOADS_DIR}"
[[ -d "${PATIENT_LOGS_DIR}" ]] || die "Patient logs directory not found: ${PATIENT_LOGS_DIR}"
if [[ ! -f "${APP_LOG_FILE}" ]]; then
  log "App log not found at ${APP_LOG_FILE} (skipping - runtime artifact)"
  APP_LOG_FILE=""
fi

if [[ -n "${BACKUP_ENCRYPTION_KEY:-}" ]]; then
  ENCRYPTION_KEY="${BACKUP_ENCRYPTION_KEY}"
elif [[ -f "${KEY_FILE}" ]]; then
  ENCRYPTION_KEY="$(tr -d '\r\n' < "${KEY_FILE}")"
else
  die "No BACKUP_ENCRYPTION_KEY available and ${KEY_FILE} is missing"
fi

if [[ -z "${SECRET_KEY}" ]]; then
  SECRET_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(64))
PY
)"
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

printf 'BACKUP_ENCRYPTION_KEY=%s\n' "${ENCRYPTION_KEY}" > "${TMP_DIR}/migration_key.env"
chmod 600 "${TMP_DIR}/migration_key.env"

cat > "${TMP_DIR}/.env.prod" <<EOF
DOMAIN=${DOMAIN}
SECRET_KEY=${SECRET_KEY}
BACKUP_ENCRYPTION_KEY=${ENCRYPTION_KEY}
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:-}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET:-}
SMTP_HOST=${SMTP_HOST:-}
SMTP_PORT=${SMTP_PORT:-587}
SMTP_USERNAME=${SMTP_USERNAME:-}
SMTP_PASSWORD=${SMTP_PASSWORD:-}
SMTP_FROM_EMAIL=${SMTP_FROM_EMAIL:-}
SMTP_USE_TLS=${SMTP_USE_TLS:-1}
EOF
chmod 600 "${TMP_DIR}/.env.prod"

python3 - <<'PY' > "${TMP_DIR}/expected_counts.txt"
import sqlite3
conn = sqlite3.connect("clinic.db")
for table in ("patients", "appointments", "users"):
    print(f"{table}={conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")
conn.close()
PY

SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new)
SCP_CMD=(scp -o StrictHostKeyChecking=accept-new)
if [[ -n "${SSH_KEY}" ]]; then
  SSH_CMD+=(-i "${SSH_KEY}")
  SCP_CMD+=(-i "${SSH_KEY}")
fi
SSH_CMD+=("${SSH_TARGET}")

BACKUP_BASENAME="$(basename "${BACKUP_FILE}")"
REMOTE_DIR_Q="$(printf '%q' "${REMOTE_DIR}")"
REPO_URL_Q="$(printf '%q' "${REPO_URL}")"
GIT_BRANCH_Q="$(printf '%q' "${GIT_BRANCH}")"
BACKUP_BASENAME_Q="$(printf '%q' "${BACKUP_BASENAME}")"

# ---------------------------------------------------------------------------
log "Phase 1: Prepare remote staging & clone/update repo on ${SSH_TARGET}"
# ---------------------------------------------------------------------------
run_ssh_script "
set -euo pipefail
mkdir -p ~/migration_staging
chmod 700 ~/migration_staging
if ! command -v git >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y git
fi
if [[ ! -d ${REMOTE_DIR_Q}/.git ]]; then
  sudo mkdir -p ${REMOTE_DIR_Q}
  sudo chown \"\$USER\":\"\$USER\" ${REMOTE_DIR_Q}
  git clone --branch ${GIT_BRANCH_Q} ${REPO_URL_Q} ${REMOTE_DIR_Q}
else
  git -C ${REMOTE_DIR_Q} fetch origin ${GIT_BRANCH_Q}
  git -C ${REMOTE_DIR_Q} checkout ${GIT_BRANCH_Q}
  git -C ${REMOTE_DIR_Q} pull --ff-only origin ${GIT_BRANCH_Q}
fi
git -C ${REMOTE_DIR_Q} rev-parse HEAD
"

if [[ "${SKIP_DOCKER_SETUP}" == "0" ]]; then
  log "Ensuring Docker is available on the remote host"
  run_ssh_script "
set -euo pipefail
if ! command -v docker >/dev/null 2>&1; then
  cd ${REMOTE_DIR_Q}
  sudo bash scripts/setup_ubuntu_docker.sh
fi
"
fi

# ---------------------------------------------------------------------------
log "Phase 2: Upload backup, env, and data artifacts"
# ---------------------------------------------------------------------------
run_cmd "${SCP_CMD[@]}" "${BACKUP_FILE}" "${SSH_TARGET}:~/migration_staging/${BACKUP_BASENAME}"
run_cmd "${SCP_CMD[@]}" "${TMP_DIR}/migration_key.env" "${SSH_TARGET}:~/migration_staging/migration_key.env"
run_cmd "${SCP_CMD[@]}" "${TMP_DIR}/.env.prod" "${SSH_TARGET}:~/migration_staging/.env.prod"
run_cmd "${SCP_CMD[@]}" "${TMP_DIR}/expected_counts.txt" "${SSH_TARGET}:~/migration_staging/expected_counts.txt"
stream_to_remote() {
  local src_dir="$1"
  local src_name="$2"
  if [[ "${DRY_RUN}" == "1" ]]; then
    quote_cmd tar -C "${src_dir}" -cf - "${src_name}" "|" "${SSH_CMD[@]}" "mkdir -p ~/migration_staging && tar -C ~/migration_staging -xf -"
  else
    tar -C "${src_dir}" -cf - "${src_name}" | "${SSH_CMD[@]}" "mkdir -p ~/migration_staging && tar -C ~/migration_staging -xf -"
  fi
}

stream_to_remote "${ROOT_DIR}/static" uploads
stream_to_remote "${ROOT_DIR}" patients_logs
if [[ -n "${APP_LOG_FILE}" ]]; then
  run_cmd "${SCP_CMD[@]}" "${APP_LOG_FILE}" "${SSH_TARGET}:~/migration_staging/app_log.txt"
fi

# ---------------------------------------------------------------------------
log "Phase 3: Deploy app and restore data on the AWS host"
# ---------------------------------------------------------------------------
run_ssh_script "
set -euo pipefail
timestamp=\$(date +%Y%m%d_%H%M%S)
cd ${REMOTE_DIR_Q}
if [[ -f .env.prod ]]; then
  sudo cp .env.prod .env.prod.pre_migration_\${timestamp}
fi
sudo install -m 600 ~/migration_staging/.env.prod .env.prod
sudo cp .env.prod .env
sudo chmod 600 .env
sudo mkdir -p data/secure_backups data/uploads data/patients_logs
sudo cp ~/migration_staging/${BACKUP_BASENAME_Q} data/secure_backups/${BACKUP_BASENAME_Q}
if [[ -d ~/migration_staging/uploads ]]; then
  sudo cp -a ~/migration_staging/uploads/. data/uploads/
fi
if [[ -d ~/migration_staging/patients_logs ]]; then
  sudo cp -a ~/migration_staging/patients_logs/. data/patients_logs/
fi
if [[ -f ~/migration_staging/app_log.txt ]]; then
  if [[ -f data/app_log.txt ]]; then
    sudo tee -a data/app_log.txt < ~/migration_staging/app_log.txt > /dev/null
  else
    sudo cp ~/migration_staging/app_log.txt data/app_log.txt
  fi
fi
sudo bash scripts/deploy_prod.sh
for _ in \$(seq 1 30); do
  if sudo docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T app python3 -c 'print(\"ready\")' >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
sudo docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T app python3 - <<'PY'
from app import app, perform_encrypted_restore
BACKUP_FILE = '${BACKUP_BASENAME}'
with app.app_context():
    target, safety = perform_encrypted_restore('/data/clinic.db', BACKUP_FILE)
    print(f'Restored from: {target}')
    print(f'Safety copy at: {safety}')
PY
python3 - <<'PY'
import sqlite3
db_path = '${REMOTE_DIR}/data/clinic.db'
conn = sqlite3.connect(db_path)
integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
print(f'integrity={integrity}')
for table in ('patients', 'appointments', 'users'):
    print(f'{table}=' + str(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]))
conn.close()
PY
sudo docker compose --env-file .env.prod -f docker-compose.prod.yml ps
"

if [[ "${SKIP_HEALTHCHECK}" == "0" ]]; then
  log "Running final HTTPS health checks against ${DOMAIN}"
  run_cmd curl -s -o /dev/null -w "root_status=%{http_code}\n" "https://${DOMAIN}/"
  run_cmd curl -s -o /dev/null -w "admin_status=%{http_code}\n" "https://${DOMAIN}/admin/"
  run_cmd curl -s -o /dev/null -w "crm_status=%{http_code}\n" "https://${DOMAIN}/crm"
fi

log "AWS migration flow completed."
log "Expected row counts from local source:"
cat "${TMP_DIR}/expected_counts.txt"
