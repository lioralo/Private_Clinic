#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python verification/refactor_guard.py check
python -m unittest tests.test_refactor_guardrails
python -m unittest tests.test_app.ClinicTestCase.test_healthz_returns_ok_when_db_available tests.test_app.ClinicTestCase.test_healthz_returns_503_when_db_unavailable

echo "Refactor checks completed successfully."
