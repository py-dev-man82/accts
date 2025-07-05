#!/usr/bin/env bash set -e

test_features.sh

A shell script to exercise all SecureDB functionality end-to-end

1) Activate virtualenv

if [[ -f "venv/bin/activate" ]]; then source venv/bin/activate else echo "⚠️  virtualenv not found; ensure dependencies are installed" exit 1 fi

2) Run Python test block

python3 << 'EOF' import tempfile from datetime import datetime import config from secure_db import SecureDB

def run_tests(): db_path = tempfile.mktemp() db = SecureDB(db_path) tables = {}

# Test customers
cust = {"id":1, "name":"TestCustomer", "currency":"USD", "created_at": datetime.utcnow().isoformat()}
db.insert("customers", cust)
tables["customers"] = db.all("customers")

# Test stores
store = {"id":1, "name":"TestStore", "currency":"USD", "created_at": datetime.utcnow().isoformat()}
db.insert("stores", store)
tables["stores"] = db.all("stores")

# Test partners
part = {"id":1, "name":"TestPartner", "currency":"EUR", "created_at": datetime.utcnow().isoformat()}
db.insert("partners", part)
tables["partners"] = db.all("partners")

# Test items
item1 = {"id":1, "name":"Item1", "created_at": datetime.utcnow().isoformat()}
item2 = {"id":2, "name":"Item2", "created_at": datetime.utcnow().isoformat()}
db.insert("items", item1)
db.insert("items", item2)
tables["items"] = db.all("items")

# Test customer_sales
sale = {"customer_id":1, "store_id":1, "item_id":1, "qty":5, "unit_price":10.0, "note":"", "created_at": datetime.utcnow().isoformat()}
db.insert("customer_sales", sale)
tables["customer_sales"] = db.all("customer_sales")

# Test customer_payments
payment = {"customer_id":1, "local_amount":100.0, "fee":5.0, "usd_amount":95.0, "created_at": datetime.utcnow().isoformat()}
db.insert("customer_payments", payment)
tables["customer_payments"] = db.all("customer_payments")

# Test partner_payouts
payout = {"partner_id":1, "usd_amount":50.0, "created_at": datetime.utcnow().isoformat()}
db.insert("partner_payouts", payout)
tables["partner_payouts"] = db.all("partner_payouts")

# Test store_inventory
store_inv = {"store_id":1, "item_id":1, "qty":20, "created_at": datetime.utcnow().isoformat()}
db.insert("store_inventory", store_inv)
tables["store_inventory"] = db.all("store_inventory")

# Test partner_inventory
part_inv = {"partner_id":1, "item_id":2, "qty":30, "created_at": datetime.utcnow().isoformat()}
db.insert("partner_inventory", part_inv)
tables["partner_inventory"] = db.all("partner_inventory")

# Report results
all_ok = True
for name, records in tables.items():
    if not records:
        print(f"FAIL: {name} is empty")
        all_ok = False
    else:
        print(f"PASS: {name} has {len(records)} record(s)")
return all_ok

if not run_tests(): exit(1) EOF

3) Final message

if [[ $? -eq 0 ]]; then echo "✅ All feature tests passed." else echo "❌ Some feature tests failed. See above." fi

