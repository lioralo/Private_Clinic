#!/usr/bin/env bash
# =============================================================================
# deploy_local_bundle_to_aws.sh — Deploy local checkout to AWS
#
# Bundles the current local checkout (excluding runtime data) and deploys it
# to an AWS host while preserving .env, .git, and the data/ directory.
# =============================================================================

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deploy_local_bundle_to_aws.sh --ssh-target ubuntu@<server-ip> [options]

Required:
  --ssh-target TARGET      SSH target for the AWS host, e.g. ubuntu@1.2.3.4

Optional:
  --ssh-key PATH           PEM/private key path for SSH/SCP
  --remote-dir PATH        Remote repo path (default: /opt/Private_Clinic)
  --skip-healthcheck       Skip final login endpoint check
  --dry-run                Print actions without executing them

This script deploys the current local checkout to the AWS host while preserving
all runtime data under <remote-dir>/data as well as .env/.env.prod and .git.
EOF
}

die() {
  echo "[deploy_local_bundle_to_aws] ERROR: $*" >&2
  exit 1
}

log() {
  echo "[deploy_local_bundle_to_aws] $*"
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
SSH_TARGET=""
SSH_KEY=""
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
    --remote-dir)
      REMOTE_DIR="${2:-}"
      shift 2
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
[[ -d "${ROOT_DIR}/scripts" ]] || die "Could not determine repo root"

if [[ -n "${SSH_KEY}" && ! -f "${SSH_KEY}" ]]; then
  die "SSH key not found: ${SSH_KEY}"
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

ARCHIVE_PATH="${TMP_DIR}/private_clinic_bundle.tar.gz"

log "Building deployment bundle from local checkout"
run_cmd tar \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='data' \
  --exclude='clinic.db' \
  --exclude='patients_logs' \
  --exclude='secure_backups' \
  --exclude='app_log.txt' \
  -czf "${ARCHIVE_PATH}" \
  -C "${ROOT_DIR}" .

SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new)
SCP_CMD=(scp -o StrictHostKeyChecking=accept-new)
if [[ -n "${SSH_KEY}" ]]; then
  SSH_CMD+=(-i "${SSH_KEY}")
  SCP_CMD+=(-i "${SSH_KEY}")
fi
SSH_CMD+=("${SSH_TARGET}")

REMOTE_DIR_Q="$(printf '%q' "${REMOTE_DIR}")"

log "Uploading bundle to ${SSH_TARGET}"
run_cmd "${SCP_CMD[@]}" "${ARCHIVE_PATH}" "${SSH_TARGET}:~/private_clinic_bundle.tar.gz"

log "Deploying bundle while preserving runtime data"
run_ssh_script "
set -euo pipefail
mkdir -p ~/private_clinic_bundle_extract
rm -rf ~/private_clinic_bundle_extract/*
tar -xzf ~/private_clinic_bundle.tar.gz -C ~/private_clinic_bundle_extract
sudo mkdir -p ${REMOTE_DIR_Q}
sudo find ${REMOTE_DIR_Q} -mindepth 1 -maxdepth 1 \\
  ! -name '.git' ! -name '.env' ! -name '.env.prod' ! -name 'data' \\
  -exec rm -rf {} +
sudo cp -a ~/private_clinic_bundle_extract/. ${REMOTE_DIR_Q}/
cd ${REMOTE_DIR_Q}
if [[ ! -f .env && -f .env.prod ]]; then
  sudo cp .env.prod .env
  sudo chmod 600 .env
fi
if grep -q 'tls {\$TLS_EMAIL}' Caddyfile; then
  if ! sudo grep -Eq '^TLS_EMAIL=.+$' .env.prod; then
    domain=\$(sudo grep '^DOMAIN=' .env.prod | head -n1 | cut -d= -f2-)
    if [[ -z "\${domain}" ]]; then
      echo 'DOMAIN missing in .env.prod; cannot derive TLS_EMAIL' >&2
      exit 1
    fi
    tls_email=\"admin@\${domain}\"
    if sudo grep -Eq '^TLS_EMAIL=' .env.prod; then
      sudo sed -i \"s/^TLS_EMAIL=.*/TLS_EMAIL=\${tls_email}/\" .env.prod
    else
      printf '\nTLS_EMAIL=%s\n' \"\${tls_email}\" | sudo tee -a .env.prod >/dev/null
    fi
    echo \"[deploy_local_bundle_to_aws] Added missing TLS_EMAIL=\${tls_email} to .env.prod\"
  fi
fi
sudo bash scripts/deploy_prod.sh
"

if [[ "${SKIP_HEALTHCHECK}" == "0" ]]; then
  log "Checking live login endpoint"
  run_ssh_script "
set -euo pipefail
domain=\$(sudo grep '^DOMAIN=' ${REMOTE_DIR_Q}/.env.prod | head -n1 | cut -d= -f2-)
if [[ -z \"\${domain}\" ]]; then
  echo 'DOMAIN missing in .env.prod' >&2
  exit 1
fi
curl -k -s -o /dev/null -w '%{http_code}\n' --resolve \${domain}:443:127.0.0.1 https://\${domain}/login
"
fi

log "Done"
