# generate_test_data.py

import random
from datetime import datetime, timedelta
from secure_db import secure_db


def random_date_within_weeks(weeks):
    """Returns a random date string DDMMYYYY within the last `weeks`"""
    days_ago = random.randint(0, weeks * 7)
    date = datetime.now() - timedelta(days=days_ago)
    return date.strftime('%d%m%Y')


def random_currency():
    """Randomly pick a currency code"""
    return random.choice(['USD', 'EUR', 'GBP', 'JPY'])


def generate_customers(n=8):
    print(f"Adding {n} customers...")
    for i in range(1, n + 1):
        secure_db.insert('customers', {
            'name': f"Customer {i}",
            'currency': random_currency(),
            'created_at': datetime.utcnow().isoformat()
        })


def generate_stores(n=2):
    print(f"Adding {n} stores...")
    for i in range(1, n + 1):
        secure_db.insert('stores', {
            'name': f"Store {i}",
            'currency': random_currency(),
            'created_at': datetime.utcnow().isoformat()
        })


def generate_partners(n=4):
    print(f"Adding {n} partners...")
    for i in range(1, n + 1):
        secure_db.insert('partners', {
            'name': f"Partner {i}",
            'currency': random_currency(),
            'created_at': datetime.utcnow().isoformat()
        })


def generate_sales(entries_per_customer=20):
    print(f"Adding {entries_per_customer} sales per customer...")
    customers = secure_db.all('customers')
    stores = secure_db.all('stores')
    for customer in customers:
        for _ in range(entries_per_customer):
            store = random.choice(stores)
            item_id = random.choice([1, 2])  # Restrict to items 1 or 2
            qty = random.randint(1, 5)
            price = round(random.uniform(5.0, 50.0), 2)
            sale_type = random.choice(['direct', 'owner'])
            secure_db.insert('sales', {
                'customer_id': customer.doc_id,
                'store_id': store.doc_id,
                'item_id': item_id,
                'quantity': qty,
                'unit_price': price,
                'currency': store['currency'],
                'sale_type': sale_type,
                'handling_fee': round(price * qty * 0.05, 2),  # 5% fee for owner sales
                'note': f"Test sale {sale_type}",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })


def generate_payments(entries_per_customer=20):
    print(f"Adding {entries_per_customer} payments per customer...")
    customers = secure_db.all('customers')
    for customer in customers:
        for _ in range(entries_per_customer):
            local_amt = round(random.uniform(50.0, 500.0), 2)
            fee = round(local_amt * 0.02, 2)  # 2% fee
            usd_amt = round((local_amt - fee) / random.uniform(0.7, 1.3), 2)
            secure_db.insert('customer_payments', {
                'customer_id': customer.doc_id,
                'local_amt': local_amt,
                'fee_perc': 2.0,
                'fee_amt': fee,
                'usd_amt': usd_amt,
                'fx_rate': round((local_amt - fee) / usd_amt, 4),
                'note': "Test payment",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })


def generate_stockins(entries_per_partner=20):
    print(f"Adding {entries_per_partner} stock-ins per partner...")
    partners = secure_db.all('partners')
    for partner in partners:
        for _ in range(entries_per_partner):
            item_id = random.choice([1, 2])  # Restrict to items 1 or 2
            qty = random.randint(10, 100)
            cost = round(random.uniform(1.0, 10.0), 2)
            secure_db.insert('partner_inventory', {
                'partner_id': partner.doc_id,
                'item_id': item_id,
                'quantity': qty,
                'cost': cost,
                'note': "Test stock-in",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })


def generate_payouts(entries_per_partner=20):
    print(f"Adding {entries_per_partner} payouts per partner...")
    partners = secure_db.all('partners')
    for partner in partners:
        for _ in range(entries_per_partner):
            local_amt = round(random.uniform(100.0, 1000.0), 2)
            fee = round(local_amt * 0.03, 2)  # 3% fee
            usd_amt = round((local_amt - fee) / random.uniform(0.7, 1.3), 2)
            secure_db.insert('partner_payouts', {
                'partner_id': partner.doc_id,
                'local_amt': local_amt,
                'fee_perc': 3.0,
                'fee_amt': fee,
                'usd_amt': usd_amt,
                'fx_rate': round((local_amt - fee) / usd_amt, 4),
                'note': "Test payout",
                'date': random_date_within_weeks(6),
                'timestamp': datetime.utcnow().isoformat()
            })


def main():
    print("🚀 Generating test data...")
    generate_customers()
    generate_stores()
    generate_partners()
    generate_sales()
    generate_payments()
    generate_stockins()
    generate_payouts()
    print("✅ Test data generation complete!")


if __name__ == "__main__":
    main()