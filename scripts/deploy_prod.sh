#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.prod"
RUNTIME_ENV_FILE="${ROOT_DIR}/.env"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}"
  echo "Create it first with: cp .env.prod.example .env.prod"
  exit 1
fi

# Compose currently references ".env" via env_file.
# Keep it in sync from .env.prod for production deployments.
cp "${ENV_FILE}" "${RUNTIME_ENV_FILE}"
chmod 600 "${RUNTIME_ENV_FILE}" || true

required_vars=(DOMAIN SECRET_KEY BACKUP_ENCRYPTION_KEY)
for key in "${required_vars[@]}"; do
  if ! grep -Eq "^${key}=.+$" "${ENV_FILE}"; then
    echo "Missing ${key} in .env.prod"
    exit 1
  fi
done

if grep -Eq '^DOMAIN=clinic\.example\.com$' "${ENV_FILE}" || \
   grep -Eq '^SECRET_KEY=replace-with-a-long-random-secret$' "${ENV_FILE}" || \
   grep -Eq '^BACKUP_ENCRYPTION_KEY=replace-with-a-base64-fernet-key$' "${ENV_FILE}"; then
  echo ".env.prod still contains placeholder values."
  echo "Edit it before deploying."
  exit 1
fi

if command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "Starting production stack..."
cd "${ROOT_DIR}"
${SUDO} docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --build

echo
echo "Deployment started. Check status with:"
echo "  ${SUDO} docker compose --env-file .env.prod -f docker-compose.prod.yml ps"
echo "  ${SUDO} docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f"
