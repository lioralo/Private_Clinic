#!/usr/bin/env bash
# =============================================================================
# deploy_with_verify.sh — Comprehensive AWS deployment with verification
#
# This script handles:
# 1. Local state verification (branch, commit, git diff)
# 2. Encrypted backup creation
# 3. AWS migration (clones/updates repo, restores DB, starts services)
# 4. Deployment of local bundle to AWS
# 5. Remote verification (git commit, Docker containers, service health)
# 6. HTTPS endpoint health checks
#
# USAGE:
#   export SERVER_IP=13.61.60.244
#   export SSH_KEY_PATH=/home/you/private-clinic-key.pem
#   export DOMAIN=clinic.yourdomain.com
#   bash deploy_with_verify.sh
#
# Or inline:
#   SERVER_IP=13.61.60.244 SSH_KEY_PATH=/path/to/key.pem DOMAIN=clinic.com bash deploy_with_verify.sh
# =============================================================================

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
  echo -e "${BLUE}[deploy]${NC} $*"
}

log_success() {
  echo -e "${GREEN}[deploy]${NC} ✓ $*"
}

log_warn() {
  echo -e "${YELLOW}[deploy]${NC} ⚠ $*"
}

log_error() {
  echo -e "${RED}[deploy]${NC} ✗ ERROR: $*" >&2
}

die() {
  log_error "$@"
  exit 1
}

# Verify required environment variables
if [[ -z "${SERVER_IP:-}" ]]; then
  die "Missing SERVER_IP environment variable"
fi
if [[ -z "${SSH_KEY_PATH:-}" ]]; then
  die "Missing SSH_KEY_PATH environment variable"
fi
if [[ -z "${DOMAIN:-}" ]]; then
  die "Missing DOMAIN environment variable"
fi

# Verify SSH key exists
if [[ ! -f "${SSH_KEY_PATH}" ]]; then
  die "SSH key not found: ${SSH_KEY_PATH}"
fi

# Get script directory and navigate to repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

log_info "Deployment Config:"
log_info "  Server: ubuntu@${SERVER_IP}"
log_info "  Domain: ${DOMAIN}"
log_info "  SSH Key: ${SSH_KEY_PATH}"
log_info ""

# ============================================================================
# STEP 1: Local State Verification
# ============================================================================
log_info "STEP 1: Verifying local git state..."

LOCAL_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
if [[ "${LOCAL_BRANCH}" == "HEAD" ]]; then
  LOCAL_BRANCH="main"
fi

LOCAL_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
LOCAL_TAG=$(git describe --tags --always 2>/dev/null || echo "none")

log_info "  Branch: ${LOCAL_BRANCH}"
log_info "  Commit: ${LOCAL_COMMIT}"
log_info "  Tag: ${LOCAL_TAG}"

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
  log_warn "Local changes detected (will be deployed as-is)"
  git status --short
else
  log_success "Working directory clean"
fi

echo ""

# ============================================================================
# STEP 2: Create Encrypted Backup
# ============================================================================
log_info "STEP 2: Creating encrypted database backup..."

if [[ -f "scripts/backup_db.py" ]]; then
  python3 scripts/backup_db.py || die "Backup failed"
  log_success "Backup created"
else
  log_warn "scripts/backup_db.py not found, skipping backup step"
fi

echo ""

# ============================================================================
# STEP 3: AWS Migration
# ============================================================================
log_info "STEP 3: Running AWS migration (app setup, DB restore, services start)..."

if [[ -f "scripts/migrate_to_aws.sh" ]]; then
  bash scripts/migrate_to_aws.sh \
    --ssh-target "ubuntu@${SERVER_IP}" \
    --ssh-key "${SSH_KEY_PATH}" \
    --domain "${DOMAIN}" \
    || die "Migration failed"
  log_success "Migration completed"
else
  log_warn "scripts/migrate_to_aws.sh not found, skipping migration"
fi

echo ""

# ============================================================================
# STEP 4: Deploy Local Bundle
# ============================================================================
log_info "STEP 4: Uploading local checkout bundle to AWS..."

if [[ -f "scripts/deploy_local_bundle_to_aws.sh" ]]; then
  bash scripts/deploy_local_bundle_to_aws.sh \
    --ssh-target "ubuntu@${SERVER_IP}" \
    --ssh-key "${SSH_KEY_PATH}" \
    || die "Bundle deployment failed"
  log_success "Local bundle deployed"
else
  log_warn "scripts/deploy_local_bundle_to_aws.sh not found, skipping bundle deployment"
fi

echo ""

# ============================================================================
# STEP 5: Remote Verification
# ============================================================================
log_info "STEP 5: Verifying remote state..."

REMOTE_COMMIT=$(ssh -i "${SSH_KEY_PATH}" \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=10 \
  "ubuntu@${SERVER_IP}" \
  "cd /opt/Private_Clinic && git rev-parse HEAD 2>/dev/null || echo 'unknown'" \
  || echo "ssh-error")

if [[ "${REMOTE_COMMIT}" == "ssh-error" ]]; then
  log_error "Failed to SSH to remote host"
else
  if [[ "${REMOTE_COMMIT}" == "${LOCAL_COMMIT}" ]]; then
    log_success "Remote commit matches local: ${REMOTE_COMMIT}"
  else
    log_warn "Remote commit differs from local"
    log_info "  Local:  ${LOCAL_COMMIT}"
    log_info "  Remote: ${REMOTE_COMMIT}"
  fi
fi

echo ""

# ============================================================================
# STEP 6: Docker Services Health Check
# ============================================================================
log_info "STEP 6: Checking Docker services..."

DOCKER_OUTPUT=$(ssh -i "${SSH_KEY_PATH}" \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=10 \
  "ubuntu@${SERVER_IP}" \
  "cd /opt/Private_Clinic && sudo docker compose --env-file .env.prod -f docker-compose.prod.yml ps 2>/dev/null || echo 'docker-error'" \
  || echo "ssh-error")

if [[ "${DOCKER_OUTPUT}" == "docker-error" ]] || [[ "${DOCKER_OUTPUT}" == "ssh-error" ]]; then
  log_warn "Could not query Docker services"
else
  echo "${DOCKER_OUTPUT}"
fi

echo ""

# ============================================================================
# STEP 7: Application Logs
# ============================================================================
log_info "STEP 7: Retrieving recent application logs (last 50 lines)..."

LOGS=$(ssh -i "${SSH_KEY_PATH}" \
  -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=10 \
  "ubuntu@${SERVER_IP}" \
  "cd /opt/Private_Clinic && sudo docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=50 app caddy 2>/dev/null || echo 'logs-error'" \
  || echo "ssh-error")

if [[ "${LOGS}" != "ssh-error" ]] && [[ "${LOGS}" != "logs-error" ]]; then
  echo "${LOGS}" | tail -30
else
  log_warn "Could not retrieve logs"
fi

echo ""

# ============================================================================
# STEP 8: HTTPS Health Checks
# ============================================================================
log_info "STEP 8: Running HTTPS endpoint health checks..."

check_endpoint() {
  local endpoint=$1
  local label=$2
  local status=$(curl -s -o /dev/null -w "%{http_code}" \
    -m 10 \
    "https://${DOMAIN}${endpoint}" \
    2>/dev/null || echo "000")
  
  if [[ "${status}" == "200" ]] || [[ "${status}" == "301" ]] || [[ "${status}" == "302" ]]; then
    log_success "${label}: HTTP ${status}"
  else
    log_warn "${label}: HTTP ${status}"
  fi
}

check_endpoint "/" "Homepage"
check_endpoint "/admin/" "Admin Portal"
check_endpoint "/crm" "CRM Interface"

echo ""

# ============================================================================
# SUMMARY
# ============================================================================
log_success "Deployment verification complete!"
log_info "Summary:"
log_info "  Local Branch: ${LOCAL_BRANCH}"
log_info "  Local Commit: ${LOCAL_COMMIT}"
log_info "  Remote Commit: ${REMOTE_COMMIT}"
log_info "  Domain: https://${DOMAIN}/"
log_info ""
log_info "Next steps:"
log_info "  1. Visit https://${DOMAIN}/ to verify the site is live"
log_info "  2. Check admin portal at https://${DOMAIN}/admin/"
log_info "  3. Monitor logs: ssh -i ${SSH_KEY_PATH} ubuntu@${SERVER_IP}"
log_info "     Then: cd /opt/Private_Clinic && docker compose logs -f"

exit 0
