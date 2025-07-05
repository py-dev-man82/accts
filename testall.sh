#!/usr/bin/env bash
set -e

# testall.sh — run ALL pytest tests in tests/ and capture into test_report.txt

# 1) cd into project root (script’s directory)
cd "$(dirname "$0")"

# 2) Activate virtualenv
if [[ -f "venv/bin/activate" ]]; then
  # no spaces here!
  source venv/bin/activate
else
  echo "⚠️  virtualenv not found; please run setup_bot.sh first"
  exit 1
fi

# 3) Run pytest and capture everything
REPORT="test_report.txt"
echo "=== TEST RUN START: $(date) ===" > "$REPORT"
pytest -v tests/ --disable-warnings --maxfail=1 >> "$REPORT" 2>&1 || true
echo "" >> "$REPORT"
echo "=== TEST RUN END:   $(date) ===" >> "$REPORT"

echo "✅ Tests complete. See $REPORT for details."