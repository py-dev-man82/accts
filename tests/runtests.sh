#!/usr/bin/env bash set -e

-----------------------------

run_tests.sh

-----------------------------

Discovers and runs pytest suite, logs output to test_report.txt

1) Determine project root (script directory)

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" cd "$PROJECT_DIR"

2) Ensure tests directory exists

if [[ ! -d "tests" ]]; then echo "ERROR: tests/ directory not found in $PROJECT_DIR" exit 1 fi

3) Activate virtualenv

if [[ -f "venv/bin/activate" ]]; then

shellcheck disable=SC1091

source venv/bin/activate else echo "WARNING: venv not found, proceeding with system Python" fi

4) Install or upgrade pytest

pip install --upgrade pytest pytest-asyncio > /dev/null

5) Run pytest and capture output

REPORT_FILE="${PROJECT_DIR}/test_report.txt" echo "=== TEST RUN START: $(date '+%Y-%m-%d %H:%M:%S') ===" > "$REPORT_FILE" pytest --maxfail=1 --disable-warnings >> "$REPORT_FILE" 2>&1 || true

echo "" >> "$REPORT_FILE" echo "=== TEST RUN END: $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$REPORT_FILE"

6) Display summary

echo "Test results written to $REPORT_FILE" if grep -q "FAILURES" "$REPORT_FILE"; then echo "❌ Some tests failed. Check the report." exit 1 else echo "✅ All tests passed." exit 0 fi

