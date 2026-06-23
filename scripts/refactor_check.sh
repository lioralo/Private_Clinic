#!/usr/bin/env bash
# =============================================================================
# refactor_check.sh — Run refactor guard + related tests
#
# Snapshot and check route contracts, then run refactor guardrails and health
# endpoint tests to verify nothing broke during modularization.
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "=== Route contract check ==="
python verification/refactor_guard.py check

echo "=== Refactor guardrails tests ==="
python -m unittest tests.test_refactor_guardrails

echo "=== Health endpoint tests ==="
python -m unittest tests.test_app.ClinicTestCase.test_healthz_returns_ok_when_db_available \
  tests.test_app.ClinicTestCase.test_healthz_returns_503_when_db_unavailable

echo ""
echo "All refactor checks passed."
