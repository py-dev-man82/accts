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

def compute_store_sales(secure_db, get_ledger, start=None, end=None):
    sales = defaultdict(lambda: defaultdict(list))
    for store in secure_db.all("stores"):
        for e in get_ledger("store", store.doc_id):
            if e.get("entry_type") == "sale":
                if start and end:
                    dt = e.get("date", "")
                    try:
                        dt_obj = datetime.strptime(dt, "%d%m%Y")
                        if not (start <= dt_obj <= end):
                            continue
                    except Exception:
                        continue
                item_id = e.get("item_id", "?")
                sales[store.doc_id][item_id].append(e)
    return sales

def compute_store_handling_fees(secure_db, get_ledger, start=None, end=None):
    fees = defaultdict(lambda: defaultdict(list))
    for store in secure_db.all("stores"):
        for e in get_ledger("store", store.doc_id):
            if e.get("entry_type") == "handling_fee":
                if start and end:
                    dt = e.get("date", "")
                    try:
                        dt_obj = datetime.strptime(dt, "%d%m%Y")
                        if not (start <= dt_obj <= end):
                            continue
                    except Exception:
                        continue
                item_id = e.get("item_id", "?")
                fees[store.doc_id][item_id].append(e)
    return fees

def compute_store_payments(secure_db, get_ledger, store_customer_ids=None, start=None, end=None):
    # store_customer_ids: dict[store_id] = [customer_ids]
    payments = defaultdict(list)
    for store in secure_db.all("stores"):
        cust_ids = []
        if store_customer_ids and store.doc_id in store_customer_ids:
            cust_ids = store_customer_ids[store.doc_id]
        else:
            # fallback: match customer name to store name
            cust_ids = [c.doc_id for c in secure_db.all("customers") if c.get("name") == store.get("name")]
        for cust_id in cust_ids:
            for acct_type in ["customer", "store_customer"]:
                for e in get_ledger(acct_type, cust_id):
                    if e.get("entry_type") == "payment":
                        if start and end:
                            dt = e.get("date", "")
                            try:
                                dt_obj = datetime.strptime(dt, "%d%m%Y")
                                if not (start <= dt_obj <= end):
                                    continue
                            except Exception:
                                continue
                        payments[store.doc_id].append(e)
    return payments

def compute_store_expenses(secure_db, get_ledger, start=None, end=None):
    expenses = defaultdict(list)
    for store in secure_db.all("stores"):
        for e in get_ledger("store", store.doc_id):
            if e.get("entry_type") == "expense":
                if start and end:
                    dt = e.get("date", "")
                    try:
                        dt_obj = datetime.strptime(dt, "%d%m%Y")
                        if not (start <= dt_obj <= end):
                            continue
                    except Exception:
                        continue
                expenses[store.doc_id].append(e)
    return expenses

def compute_store_stockins(secure_db, get_ledger, start=None, end=None):
    stockins = defaultdict(list)
    for store in secure_db.all("stores"):
        # stockins from store ledger
        for e in get_ledger("store", store.doc_id):
            if e.get("entry_type") == "stockin":
                if start and end:
                    dt = e.get("date", "")
                    try:
                        dt_obj = datetime.strptime(dt, "%d%m%Y")
                        if not (start <= dt_obj <= end):
                            continue
                    except Exception:
                        continue
                stockins[store.doc_id].append(e)
        # stockins from partner ledger where store_id matches
        for partner in secure_db.all("partners"):
            for e in get_ledger("partner", partner.doc_id):
                if e.get("entry_type") == "stockin" and e.get("store_id") == store.doc_id:
                    if start and end:
                        dt = e.get("date", "")
                        try:
                            dt_obj = datetime.strptime(dt, "%d%m%Y")
                            if not (start <= dt_obj <= end):
                                continue
                        except Exception:
                            continue
                    stockins[store.doc_id].append(e)
    return stockins
