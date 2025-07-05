# tests/test_all.py

import pytest
import tempfile
from datetime import datetime

import config
from secure_db import SecureDB

# A list of (table_name, sample_doc) to iterate over
TEST_DOCS = [
    ("customers",       {"name": "Acme Corp",   "currency": "USD", "created_at": datetime.utcnow().isoformat()}),
    ("stores",          {"name": "Main Store",  "currency": "EUR", "created_at": datetime.utcnow().isoformat()}),
    ("partners",        {"name": "Partner Co",  "currency": "GBP", "created_at": datetime.utcnow().isoformat()}),
    ("items",           {"name": "Widget",      "created_at": datetime.utcnow().isoformat()}),
    ("customer_sales",  {"customer_id":1,"store_id":1,"item_id":1,"qty":5,"unit_price":9.99,"note":"","created_at":datetime.utcnow().isoformat()}),
    ("customer_payments",{"customer_id":1,"local_amount":100.0,"fee":5.0,"usd_amount":95.0,"created_at":datetime.utcnow().isoformat()}),
    ("partner_payouts", {"partner_id":1,"usd_amount":50.0,"created_at":datetime.utcnow().isoformat()}),
    ("store_inventory", {"store_id":1,"item_id":1,"qty":100,"created_at":datetime.utcnow().isoformat()}),
    ("partner_inventory",{"partner_id":1,"item_id":2,"qty":200,"created_at":datetime.utcnow().isoformat()}),
]

@pytest.fixture
def db(tmp_path):
    # fresh SecureDB per test
    db_file = tmp_path / "test_db.json"
    cfg = SecureDB(str(db_file))
    # ensure test mode (unencrypted)
    config.ENABLE_ENCRYPTION = False
    return cfg

@pytest.mark.parametrize("table,doc", TEST_DOCS)
def test_insert_and_retrieve(db, table, doc):
    # Insert one document, then fetch
    db.insert(table, doc)
    results = db.all(table)
    assert any(all(item[k] == v for k, v in doc.items()) for item in results), \
        f"Table '{table}' did not contain {doc}"
