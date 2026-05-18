#!/usr/bin/env bash
# =============================================================================
# deploy_interactive.sh — Interactive deployment prompt
#
# This script prompts for AWS deployment credentials, then runs the full
# automated verification and deployment.
# =============================================================================

set -euo pipefail

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Private Clinic — AWS Deployment (Interactive Mode)          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Default SSH key
DEFAULT_SSH_KEY="/home/lioraloni/Downloads/private-clinic-key.pem"

# Prompt for SERVER_IP
echo "📍 Enter your AWS EC2 server public IP address:"
echo "   Example: 13.61.60.244"
read -p "   SERVER_IP: " SERVER_IP

if [[ -z "${SERVER_IP}" ]]; then
  echo "❌ SERVER_IP cannot be empty"
  exit 1
fi

# Prompt for DOMAIN
echo ""
echo "🌐 Enter your production domain (without https://):"
echo "   Example: clinic.yourdomain.com"
read -p "   DOMAIN: " DOMAIN

if [[ -z "${DOMAIN}" ]]; then
  echo "❌ DOMAIN cannot be empty"
  exit 1
fi

# Prompt for SSH_KEY_PATH with default
echo ""
echo "🔑 Enter the path to your SSH private key:"
echo "   (Press Enter to use default: ${DEFAULT_SSH_KEY})"
read -p "   SSH_KEY_PATH [${DEFAULT_SSH_KEY}]: " SSH_KEY_PATH

SSH_KEY_PATH="${SSH_KEY_PATH:-${DEFAULT_SSH_KEY}}"

# Verify SSH key exists
if [[ ! -f "${SSH_KEY_PATH}" ]]; then
  echo "❌ SSH key not found: ${SSH_KEY_PATH}"
  exit 1
fi

# Summary
echo ""
echo "✅ Configuration:"
echo "   SERVER_IP:    ${SERVER_IP}"
echo "   DOMAIN:       ${DOMAIN}"
echo "   SSH_KEY_PATH: ${SSH_KEY_PATH}"
echo ""
read -p "Continue with deployment? (yes/no): " CONFIRM

if [[ "${CONFIRM}" != "yes" ]]; then
  echo "Cancelled."
  exit 0
fi

echo ""
echo "🚀 Starting deployment..."
echo ""

# Run the main deployment script
export SERVER_IP
export SSH_KEY_PATH
export DOMAIN

bash deploy_with_verify.sh
