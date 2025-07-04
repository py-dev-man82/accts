import pytest
import os
import config
from secure_db import SecureDB

@pytest.fixture(scope="session")
def db(tmp_path_factory):
    # point to a temp file for testing
    path = tmp_path_factory.mktemp("data") / "test_db.json"
    db = SecureDB(str(path), config.DB_PASSPHRASE)
    yield db
""",
    'tests/test_smoke_imports.py': """import pytest

HANDLER_MODULES = [
    "handlers.customers",
    "handlers.stores",
    "handlers.partners",
    "handlers.sales",
    "handlers.payments",
    "handlers.payouts",
    "handlers.stockin",
    "handlers.reports",
    "handlers.export_excel",
    "handlers.export_pdf",
]

@pytest.mark.parametrize("module", HANDLER_MODULES)
def test_import_module(module):
    __import__(module)
""",
    'tests/test_secure_db_crud.py': """from datetime import datetime

def test_db_crud(db):
    # insert and retrieve one record in each table
    for table in ["customers", "stores", "partners"]:
        db.insert(table, {"foo": "bar", "ts": datetime.utcnow().isoformat()})
        results = db.all(table)
        assert any(r.get("foo") == "bar" for r in results)
""",
    'run_tests.sh': """#!/usr/bin/env bash
set -e

REPORT="test_report.txt"
echo "=== TEST RUN START: $(date) ===" > "$REPORT"

# Activate virtualenv
source venv/bin/activate

# Ensure pytest is installed
pip install pytest pytest-asyncio

# Run tests and capture output
pytest -q --disable-warnings --maxfail=1 >> "$REPORT" 2>&1 || true

echo "" >> "$REPORT"
echo "=== TEST RUN END: $(date) ===" >> "$REPORT"

echo "Test execution finished. See $REPORT for details."
"""
}

# Write files to /mnt/data
for rel_path, content in files.items():
    full_path = os.path.join('/mnt/data', rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w') as f:
        f.write(content)

# Provide links
links = [f"sandbox:/mnt/data/{rel_path}" for rel_path in files]
links