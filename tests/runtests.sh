#!/usr/bin/env bash
set -e

# -----------------------------
# run_tests.sh
# -----------------------------
# Discovers and runs pytest suite, logs output to test_report.txt

# 1) Determine project root (parent of this script's directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 2) Ensure tests directory exists
if [[ ! -d "tests" ]]; then
  echo "ERROR: tests/ directory not found in $PROJECT_ROOT"
  exit 1
fi

# 3) Activate virtualenv
if [[ -f "venv/bin/activate" ]]; then
  source venv/bin/activate
else
  echo "WARNING: virtualenv not found, proceeding without venv"
fi

# 4) Install pytest if missing
pip install pytest pytest-asyncio --quiet

# 5) Run pytest and redirect output
REPORT="test_report.txt"
echo "=== TEST RUN START: $(date) ===" > "$REPORT"
pytest -q --disable-warnings --maxfail=1 >> "$REPORT" 2>&1 || true
echo "" >> "$REPORT"
echo "=== TEST RUN END: $(date) ===" >> "$REPORT"

echo "✅ Tests complete. Results in $REPORT"