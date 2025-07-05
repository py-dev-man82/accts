#!/usr/bin/env bash
set -e

# testall.sh — run all pytest suites and capture into test_report.txt

# 1) Ensure we’re in project root
cd "$(dirname "$0")"

# 2) Activate virtualenv
if [[ -f "venv/bin/activate" ]]; then
  source venv/bin/activate
else
  echo "⚠️  venv not found—make sure you ran setup_bot.sh"
  exit 1
fi

# 3) Run pytest on your test files
REPORT="test_report.txt"
echo "=== TEST RUN START: $(date) ===" > "$REPORT"

pytest -v tests/conftest.py tests/test_secure_db_crud.py tests/test_all.py \
    --disable-warnings --maxfail=1 >> "$REPORT" 2>&1 || true

echo "" >> "$REPORT"
echo "=== TEST RUN END: $(date) ===" >> "$REPORT"

echo "✅ Tests complete. See $REPORT for details."