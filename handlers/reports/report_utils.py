from collections import defaultdict

def compute_store_inventory(secure_db, get_ledger):
    inventory = {}
    for store in secure_db.all("stores"):
        stock = defaultdict(int)
        for e in get_ledger("store", store.doc_id):
            item_id = e.get("item_id", "?")
            if e.get("entry_type") == "stockin":
                stock[item_id] += e.get("quantity", 0)
            elif e.get("entry_type") == "sale":
                stock[item_id] -= abs(e.get("quantity", 0))
        inventory[store.doc_id] = dict(stock)
    return inventory

def compute_store_sales(secure_db, get_ledger):
    sales = defaultdict(lambda: defaultdict(int))
    for store in secure_db.all("stores"):
        for e in get_ledger("store", store.doc_id):
            if e.get("entry_type") == "sale":
                item_id = e.get("item_id", "?")
                sales[store.doc_id][item_id] += abs(e.get("quantity", 0))
    return sales

def compute_partner_sales(secure_db, get_ledger):
    partner_sales = defaultdict(lambda: defaultdict(int))
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "sale":
                item_id = e.get("item_id", "?")
                partner_sales[partner.doc_id][item_id] += abs(e.get("quantity", 0))
    return partner_sales

def compute_payouts(secure_db, get_ledger):
    payouts = []
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") in ("payout", "payment_sent"):
                payouts.append(e)
    return payouts
