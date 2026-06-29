#!/usr/bin/env bash
# =============================================================================
# security_check.sh — Automated Security Code & Dependency Scan
#
# Runs Bandit for static code analysis (SAST) and pip-audit for checking
# vulnerable dependencies, ensuring compliance with High Security tier guidelines.
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [[ -d "../venv" ]]; then
  # shellcheck disable=SC1091
  source ../venv/bin/activate
fi

# Ensure Bandit is installed
if ! command -v bandit &> /dev/null; then
  echo "Bandit is not installed. Installing it..."
  pip install bandit
fi

# Ensure pip-audit is installed
if ! command -v pip-audit &> /dev/null; then
  echo "pip-audit is not installed. Installing it..."
  pip install pip-audit
fi

echo "=========================================="
echo "🛡️  Running Bandit Security Code Scan (SAST)"
echo "=========================================="
# Scan code excluding tests and virtual environments
bandit -r app.py clinic_app/ -ll -ii

echo ""
echo "=========================================="
echo "📦  Running pip-audit Dependency Vulnerability Scan"
echo "=========================================="
# Scan dependencies
pip-audit -r requirements.txt

echo ""
echo "✨ All automated security scans completed successfully."
