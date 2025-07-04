#!/usr/bin/env bash
set -e

-----------------------------

run_tests.sh

-----------------------------

Discovers and runs pytest suite, logs output to test_report.txt

1) Determine project root (parent of this script's directory)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)" cd "$PROJECT_ROOT"

2) Ensure tests directory exists

if [[ ! -d "tests" ]]; then echo "ERROR: tests/ directory not found in $PROJECT_ROOT" exit 1 fi

3) Activate virtualenv if present

if [[ -f "venv/bin/activate" ]]; then

shellcheck disable=SC1091

source venv/bin/activate else echo "WARNING: venv not found at $PROJECT_ROOT/venv, proceeding without activation" fi

4) Ensure pytest is installed

pip install --upgrade pip pip install pytest pytest-asyncio

5) Run pytest and capture output

REPORT="$PROJECT_ROOT/test_report.txt" echo "=== TEST RUN START: $(date) ===" > "$REPORT" pytest -q --disable-warnings --maxfail=1 >> "$REPORT" 2>&1 || true

echo "" >> "$REPORT" echo "=== TEST RUN END: $(date) ===" >> "$REPORT"

6) Summary

echo "Test execution finished. See $REPORT for details."

