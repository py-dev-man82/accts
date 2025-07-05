#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"
source venv/bin/activate

REPORT="test_report.txt"
echo "=== TEST RUN START: $(date) ===" > "$REPORT"
pytest -v tests/ --disable-warnings --maxfail=1 >> "$REPORT" 2>&1 || true
echo "" >> "$REPORT"
echo "=== TEST RUN END:   $(date) ===" >> "$REPORT"

echo "✅ Tests complete. See $REPORT"