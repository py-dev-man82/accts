# generate_test_data.py

import random
from datetime import datetime, timedelta
from secure_db import secure_db


# Fixed account names
CUSTOMER_NAMES = ["MK", "HT", "WP", "QW", "RB"]
PARTNER_NAMES = ["GS", "AR", "BP", "XT"]
STORE_NAMES = ["MT", "AM"]


def random_date_within_weeks(weeks):
    """Returns a random date string DDMMYYYY within the last `weeks`"""
    days_ago = random.randint(0, weeks * 7)
    date = datetime.now() - timedelta(days=days_ago)
    return date.strftime('%d%m%Y')


def random_currency():
    """Randomly pick a currency code"""
    return random.choice(['USD', 'EUR', 'GBP', 'JPY'])


def reset_database():
    """Wipe all tables in TinyDB"""
    print("⚠️ Clearing all existing database tables...")
    secure_db.table('customers').truncate()
    secure_db.table('partners').truncate()
    secure_db.table('stores').truncate()
    secure_db.table('sales').truncate()
    secure_db.table('customer_payments').truncate()
    secure_db.table('partner_inventory').truncate()
    secure_db.table('partner_payouts').truncate()
    print("✅ Database reset complete.")


def ensure_customers():
    """Create fixed customers"""
    print("🔄 Checking customers...")
    existing = {c['name']: c.doc_id for c in secure_db.all('customers')}
    for name in CUSTOMER_NAMES:
        if name not in existing:
            cid = secure_db.insert('customers', {
                'name': name,
                'currency': random_currency(),
                'created_at': datetime.utcnow().isoformat()
            })
            existing[name] = cid
    return existing


def ensure_partners():
    """Create fixed partners"""
    print("🔄 Checking partners...")
    existing = {p['name']: p.doc_id for p in secure_db.all('partners')}
    for name in PARTNER_NAMES:
        if name not in existing:
            pid = secure_db.insert('partners', {
                'name': name,
                'currency': random_currency(),
                'created_at': datetime.utcnow().isoformat()
            })
            existing[name] = pid
    return existing


def ensure_stores():
    """Create fixed stores"""
    print("🔄 Checking stores...")
    existing = {s['name']: s.doc_id for s in secure_db.all('stores')}
    for name in STORE_NAMES:
        if name not in existing:
            sid = secure_db.insert('stores', {
                'name': name,
                'currency': random_currency(),
                'created_at': datetime.utcnow().isoformat()
            })
            existing[name] = sid
    return existing


def generate_stockins(entries=25, partners=None, stores=None):
    """Generate stock-in entries"""
    print(f"📦 Adding {entries} stock-in entries...")
    for _ in range(entries):
        partner_id = random.choice(list(partners.values()))
        store_id = random.choice(list(stores.values()))
        item_id = random.choice([1, 2])
        qty = random.randint(10, 100)
        cost = round(random.uniform(1.0, 10.0), 2)
        secure_db.insert('partner_inventory', {
            'partner_id': partner_id,
            'store_id': store_id,
            'item_id': item_id,
            'quantity': qty,
            'cost': cost,
            'note': "Generated stock-in",
            'date': random_date_within_weeks(6),
            'timestamp': datetime.utcnow().isoformat()
        })


def generate_sales_and_payments(customers, stores):
    """Generate 8 sales + 8 payments per customer"""
    print(f"💰 Adding sales & payments for {len(customers)} customers...")
    for cust_name, cust_id in customers.items():
        for _ in range(8):
            store_id = random.choice(list(stores.values()))
            item_id = random.choice([1, 2])
            qty = random.randint(1, 5)
            price = round(random.uniform(5.0, 50.0), 2)
            sale_type = random.choice(['direct', 'owner'])
            secure_db.insert('sales', {
                'customer_id': cust_id,
                'store_id': store_id,
                'item_id': item_id,
                'quantity': qty,
                'unit_price': price,
                'currency': secure_db.table('stores').get(doc_id=store_id)['currency'],
                'sale_type': sale_type,
                'handling_fee': round(price * qty * 0.05, 2),  # 5% fee for owner sales
                'note': f"Generated sale ({sale_type})",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })

        for _ in range(8):
            local_amt = round(random.uniform(50.0, 500.0), 2)
            fee = round(local_amt * 0.02, 2)  # 2% fee
            usd_amt = round((local_amt - fee) / random.uniform(0.7, 1.3), 2)
            secure_db.insert('customer_payments', {
                'customer_id': cust_id,
                'local_amt': local_amt,
                'fee_perc': 2.0,
                'fee_amt': fee,
                'usd_amt': usd_amt,
                'fx_rate': round((local_amt - fee) / usd_amt, 4),
                'note': "Generated payment",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })


def generate_payouts(partners):
    """Generate 5 payouts per partner"""
    print(f"🏦 Adding payouts for {len(partners)} partners...")
    for partner_name, partner_id in partners.items():
        for _ in range(5):
            local_amt = round(random.uniform(100.0, 1000.0), 2)
            fee = round(local_amt * 0.03, 2)  # 3% fee
            usd_amt = round((local_amt - fee) / random.uniform(0.7, 1.3), 2)
            secure_db.insert('partner_payouts', {
                'partner_id': partner_id,
                'local_amt': local_amt,
                'fee_perc': 3.0,
                'fee_amt': fee,
                'usd_amt': usd_amt,
                'fx_rate': round((local_amt - fee) / usd_amt, 4),
                'note': "Generated payout",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })


def main():
    print("🚀 Test Data Generator")
    choice = input("⚠️ Reset database before generating? (y/n): ").strip().lower()
    if choice == 'y':
        reset_database()

    customers = ensure_customers()
    partners = ensure_partners()
    stores = ensure_stores()

    generate_stockins(entries=25, partners=partners, stores=stores)
    generate_sales_and_payments(customers, stores)
    generate_payouts(partners)
    print("✅ Test data generation complete!")


if __name__ == "__main__":
    main()# generate_test_data.py

import random
from datetime import datetime, timedelta
from secure_db import secure_db


# Fixed account names
CUSTOMER_NAMES = ["MK", "HT", "WP", "QW", "RB"]
PARTNER_NAMES = ["GS", "AR", "BP", "XT"]
STORE_NAMES = ["MT", "AM"]


def random_date_within_weeks(weeks):
    """Returns a random date string DDMMYYYY within the last `weeks`"""
    days_ago = random.randint(0, weeks * 7)
    date = datetime.now() - timedelta(days=days_ago)
    return date.strftime('%d%m%Y')


def random_currency():
    """Randomly pick a currency code"""
    return random.choice(['USD', 'EUR', 'GBP', 'JPY'])


def reset_database():
    """Wipe all tables in TinyDB"""
    print("⚠️ Clearing all existing database tables...")
    secure_db.table('customers').truncate()
    secure_db.table('partners').truncate()
    secure_db.table('stores').truncate()
    secure_db.table('sales').truncate()
    secure_db.table('customer_payments').truncate()
    secure_db.table('partner_inventory').truncate()
    secure_db.table('partner_payouts').truncate()
    print("✅ Database reset complete.")


def ensure_customers():
    """Create fixed customers"""
    print("🔄 Checking customers...")
    existing = {c['name']: c.doc_id for c in secure_db.all('customers')}
    for name in CUSTOMER_NAMES:
        if name not in existing:
            cid = secure_db.insert('customers', {
                'name': name,
                'currency': random_currency(),
                'created_at': datetime.utcnow().isoformat()
            })
            existing[name] = cid
    return existing


def ensure_partners():
    """Create fixed partners"""
    print("🔄 Checking partners...")
    existing = {p['name']: p.doc_id for p in secure_db.all('partners')}
    for name in PARTNER_NAMES:
        if name not in existing:
            pid = secure_db.insert('partners', {
                'name': name,
                'currency': random_currency(),
                'created_at': datetime.utcnow().isoformat()
            })
            existing[name] = pid
    return existing


def ensure_stores():
    """Create fixed stores"""
    print("🔄 Checking stores...")
    existing = {s['name']: s.doc_id for s in secure_db.all('stores')}
    for name in STORE_NAMES:
        if name not in existing:
            sid = secure_db.insert('stores', {
                'name': name,
                'currency': random_currency(),
                'created_at': datetime.utcnow().isoformat()
            })
            existing[name] = sid
    return existing


def generate_stockins(entries=25, partners=None, stores=None):
    """Generate stock-in entries"""
    print(f"📦 Adding {entries} stock-in entries...")
    for _ in range(entries):
        partner_id = random.choice(list(partners.values()))
        store_id = random.choice(list(stores.values()))
        item_id = random.choice([1, 2])
        qty = random.randint(10, 100)
        cost = round(random.uniform(1.0, 10.0), 2)
        secure_db.insert('partner_inventory', {
            'partner_id': partner_id,
            'store_id': store_id,
            'item_id': item_id,
            'quantity': qty,
            'cost': cost,
            'note': "Generated stock-in",
            'date': random_date_within_weeks(6),
            'timestamp': datetime.utcnow().isoformat()
        })


def generate_sales_and_payments(customers, stores):
    """Generate 8 sales + 8 payments per customer"""
    print(f"💰 Adding sales & payments for {len(customers)} customers...")
    for cust_name, cust_id in customers.items():
        for _ in range(8):
            store_id = random.choice(list(stores.values()))
            item_id = random.choice([1, 2])
            qty = random.randint(1, 5)
            price = round(random.uniform(5.0, 50.0), 2)
            sale_type = random.choice(['direct', 'owner'])
            secure_db.insert('sales', {
                'customer_id': cust_id,
                'store_id': store_id,
                'item_id': item_id,
                'quantity': qty,
                'unit_price': price,
                'currency': secure_db.table('stores').get(doc_id=store_id)['currency'],
                'sale_type': sale_type,
                'handling_fee': round(price * qty * 0.05, 2),  # 5% fee for owner sales
                'note': f"Generated sale ({sale_type})",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })

        for _ in range(8):
            local_amt = round(random.uniform(50.0, 500.0), 2)
            fee = round(local_amt * 0.02, 2)  # 2% fee
            usd_amt = round((local_amt - fee) / random.uniform(0.7, 1.3), 2)
            secure_db.insert('customer_payments', {
                'customer_id': cust_id,
                'local_amt': local_amt,
                'fee_perc': 2.0,
                'fee_amt': fee,
                'usd_amt': usd_amt,
                'fx_rate': round((local_amt - fee) / usd_amt, 4),
                'note': "Generated payment",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })


def generate_payouts(partners):
    """Generate 5 payouts per partner"""
    print(f"🏦 Adding payouts for {len(partners)} partners...")
    for partner_name, partner_id in partners.items():
        for _ in range(5):
            local_amt = round(random.uniform(100.0, 1000.0), 2)
            fee = round(local_amt * 0.03, 2)  # 3% fee
            usd_amt = round((local_amt - fee) / random.uniform(0.7, 1.3), 2)
            secure_db.insert('partner_payouts', {
                'partner_id': partner_id,
                'local_amt': local_amt,
                'fee_perc': 3.0,
                'fee_amt': fee,
                'usd_amt': usd_amt,
                'fx_rate': round((local_amt - fee) / usd_amt, 4),
                'note': "Generated payout",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })


def main():
    print("🚀 Test Data Generator")
    choice = input("⚠️ Reset database before generating? (y/n): ").strip().lower()
    if choice == 'y':
        reset_database()

    customers = ensure_customers()
    partners = ensure_partners()
    stores = ensure_stores()

    generate_stockins(entries=25, partners=partners, stores=stores)
    generate_sales_and_payments(customers, stores)
    generate_payouts(partners)
    print("✅ Test data generation complete!")


if __name__ == "__main__":
    main()