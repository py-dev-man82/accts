import logging
from datetime import datetime, timedelta
from collections import defaultdict
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import CallbackQueryHandler, ConversationHandler, ContextTypes, MessageHandler

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_ledger
from secure_db import secure_db

(
    OWNER_DATE_RANGE_SELECT,
    OWNER_CUSTOM_DATE_INPUT,
    OWNER_REPORT_SCOPE_SELECT,
    OWNER_REPORT_PAGE,
) = range(4)

_PAGE_SIZE = 2

def _between(date_str, start, end):
    try:
        dt = datetime.strptime(date_str, "%d%m%Y")
    except Exception:
        return False
    return start <= dt <= end

def owner_report_diagnostic(start, end, secure_db, get_ledger):
    print("\n==== OWNER REPORT DIAGNOSTIC ====")
    print(f"DATE RANGE: {fmt_date(start.strftime('%d%m%Y'))} to {fmt_date(end.strftime('%d%m%Y'))}")

    # 1. POT/Owner ledger (USD Account)
    pot_ledger = get_ledger("owner", "POT")
    print(f"\n[Owner POT ledger] {len(pot_ledger)} entries in ledger.")

    # 2. Payments Received (group and total)
    payments = [e for e in pot_ledger if e.get("entry_type") == "payment_recv" and _between(e["date"], start, end)]
    payments_by_person = defaultdict(lambda: {"local": 0.0, "usd": 0.0, "currency": "USD"})
    for p in payments:
        # Try to extract customer/store from note, or fallback
        person = p.get("note", "").split(" ")[0] if p.get("note") else "Unknown"
        payments_by_person[person]["usd"] += p.get("usd_amt", 0.0)
        payments_by_person[person]["local"] += p.get("amount", 0.0)
        payments_by_person[person]["currency"] = p.get("currency", "USD")
    print(f"\nPayments Received ({len(payments)} entries):")
    for person, v in payments_by_person.items():
        print(f"  {person}: {v['local']} {v['currency']} | {v['usd']} USD")
    print(f"  > Total USD Received: {sum(v['usd'] for v in payments_by_person.values())}")

    # 3. Payouts (group and total)
    payouts = [e for e in pot_ledger if e.get("entry_type") in ("payout", "payment_sent") and _between(e["date"], start, end)]
    payouts_by_partner = defaultdict(lambda: {"local": 0.0, "usd": 0.0, "currency": "USD"})
    for p in payouts:
        partner = p.get("note", "").split(" ")[0] if p.get("note") else "Unknown"
        payouts_by_partner[partner]["usd"] += abs(p.get("usd_amt", 0.0) or p.get("amount", 0.0))
        payouts_by_partner[partner]["local"] += abs(p.get("amount", 0.0))
        payouts_by_partner[partner]["currency"] = p.get("currency", "USD")
    print(f"\nPayouts ({len(payouts)} entries):")
    for partner, v in payouts_by_partner.items():
        print(f"  {partner}: {v['local']} {v['currency']} | {v['usd']} USD")
    print(f"  > Total USD Paid Out: {sum(v['usd'] for v in payouts_by_partner.values())}")

    # 4. Expenses
    expenses = [e for e in pot_ledger if e.get("entry_type") in ("expense", "fee") and _between(e["date"], start, end)]
    print(f"\nExpenses ({len(expenses)} entries):")
    for ex in expenses:
        print(f"  {fmt_date(ex['date'])}: {abs(ex.get('amount', 0))} {ex['currency']} ({ex.get('entry_type')})")
    print(f"  > Total Expenses: {sum(abs(e.get('amount', 0)) for e in expenses)}")

    # 5. Sales (all customers, grouped by store/item)
    print("\nSales from all customer ledgers (grouped by store/item):")
    sales_by_store_item = defaultdict(lambda: defaultdict(lambda: {"units": 0, "value": 0.0}))
    all_sales = []
    for cust in secure_db.all("customers"):
        cust_ledger = get_ledger("customer", cust.doc_id)
        for e in cust_ledger:
            if e.get("entry_type") == "sale" and _between(e.get("date", ""), start, end):
                store_id = e.get("store_id")
                item_id = e.get("item_id")
                qty = abs(e.get("quantity", 0))
                value = abs(qty * e.get("unit_price", e.get("unit_cost", 0)))
                sales_by_store_item[store_id][item_id]["units"] += qty
                sales_by_store_item[store_id][item_id]["value"] += value
                all_sales.append(e)
    for store_id, items in sales_by_store_item.items():
        store = secure_db.table("stores").get(doc_id=store_id) or {"name": f"Store {store_id}"}
        for item_id, v in items.items():
            print(f"  {store['name']}: {v['units']} units [item {item_id}] | {v['value']} USD")
    print("  > Total Sales Value: ", sum(v2["value"] for v in sales_by_store_item.values() for v2 in v.values()))

    # 6. Inventory (reconcile via ledger)
    print("\nStore Inventory (actual, from table):")
    store_inventory = secure_db.table("store_inventory").all()
    inv_actual_by_item = defaultdict(float)
    for item in store_inventory:
        inv_actual_by_item[item['item_id']] += item['quantity']
        print(f"  Item {item['item_id']}: {item['quantity']} units @ cost {item.get('unit_cost','?')} {item.get('currency','?')}")

    # Recompute from ledger (stockin and sale)
    print("\nInventory as computed from ledger (stockin and sale):")
    ledger_inv_by_item = defaultdict(float)
    # stockins
    for store in secure_db.all("stores"):
        sledger = get_ledger("store", store.doc_id)
        for e in sledger:
            if e.get("entry_type") == "stockin" and _between(e.get("date", ""), start, end):
                ledger_inv_by_item[e.get("item_id")] += e.get("quantity", 0)
    # partner stockins
    for partner in secure_db.all("partners"):
        pledger = get_ledger("partner", partner.doc_id)
        for e in pledger:
            if e.get("entry_type") == "stockin" and _between(e.get("date", ""), start, end):
                ledger_inv_by_item[e.get("item_id")] += e.get("quantity", 0)
    # sales
    for sale in all_sales:
        ledger_inv_by_item[sale.get("item_id")] -= abs(sale.get("quantity", 0))
    for item_id, qty in ledger_inv_by_item.items():
        print(f"  Item {item_id}: {qty} units (ledger computed)")

    # Reconciliation
    print("\nInventory Reconciliation Check:")
    for item_id in set(list(inv_actual_by_item.keys()) + list(ledger_inv_by_item.keys())):
        actual = inv_actual_by_item.get(item_id, 0)
        expected = ledger_inv_by_item.get(item_id, 0)
        diff = actual - expected
        if abs(diff) > 0.01:
            print(f"  ⚠️ Item {item_id}: actual={actual}, expected={expected}, DIFF={diff}")
        else:
            print(f"  Item {item_id}: OK (actual={actual}, expected={expected})")

    # Market price check
    print("\nMarket Price by item (last sale):")
    for item_id in inv_actual_by_item.keys():
        relevant_sales = [e for e in all_sales if e.get("item_id") == item_id]
        if relevant_sales:
            last_price = relevant_sales[-1].get("unit_price", relevant_sales[-1].get("unit_cost", 0))
        else:
            last_price = store_inventory[0].get("unit_cost", 0) if store_inventory else 0
        print(f"  Item {item_id}: market price = {last_price}")

    print("==== END OWNER REPORT DIAGNOSTIC ====\n")

def _reset_state(ctx):
    for k in ("start_date", "end_date", "page", "scope", "report_data"):
        ctx.user_data.pop(k, None)

def _paginate(lst, page):
    start = page * _PAGE_SIZE
    return lst[start : start + _PAGE_SIZE]

def get_last_sale_price(ledger, item_id):
    sales = [e for e in ledger if e.get("entry_type") == "sale" and e.get("item_id") == item_id]
    if sales:
        latest = sorted(sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 0))
    return 0

def _collect_report_data(start, end):
    # DIAGNOSTIC PRINTS (runs every report view)
    owner_report_diagnostic(start, end, secure_db, get_ledger)

    data = {}

    # POT = owner's USD account
    pot_ledger = get_ledger("owner", "POT")
    pot_in = sum(e["amount"] for e in pot_ledger if e.get("entry_type") == "payment_recv" and _between(e["date"], start, end))
    pot_out = sum(e["amount"] for e in pot_ledger if e.get("entry_type") in ("payout", "payment_sent") and _between(e["date"], start, end))
    pot_balance = sum(e["amount"] for e in pot_ledger)
    net_change = pot_in + pot_out  # pot_out is typically negative

    data["pot"] = {
        "balance": pot_balance,
        "inflows": pot_in,
        "outflows": abs(pot_out),
        "net": net_change,
    }

    # SALES: all stores, by item
    all_sales = []
    all_customers = secure_db.all("customers")
    all_stores = secure_db.all("stores")
    sales_by_store_item = defaultdict(lambda: defaultdict(lambda: {"units": 0, "value": 0.0}))
    for c in all_customers:
        cust_ledger = get_ledger("customer", c.doc_id)
        for s in cust_ledger:
            if s.get("entry_type") == "sale" and _between(s.get("date", ""), start, end):
                store_id = s.get("store_id")
                item_id = s.get("item_id")
                qty = abs(s.get("quantity", 0))
                value = abs(qty * s.get("unit_price", s.get("unit_cost", 0)))
                sales_by_store_item[store_id][item_id]["units"] += qty
                sales_by_store_item[store_id][item_id]["value"] += value
                all_sales.append(s)

    data["sales_by_store_item"] = sales_by_store_item

    # PAYMENTS RECEIVED: group by person (customer/store)
    payments_ledger = get_ledger("owner", "POT")
    payments_received = [e for e in payments_ledger if e.get("entry_type") == "payment_recv" and _between(e["date"], start, end)]
    payments_by_person = defaultdict(lambda: {"local": 0.0, "usd": 0.0, "currency": "USD"})
    for p in payments_received:
        customer_id = p.get("note", "").split(" ")[0] if p.get("note") else None
        usd_amt = p.get("usd_amt", 0.0)
        local_amt = p.get("amount", 0.0)
        cur = p.get("currency", "USD")
        payments_by_person[customer_id]["usd"] += usd_amt
        payments_by_person[customer_id]["local"] += local_amt
        payments_by_person[customer_id]["currency"] = cur
    total_usd_received = sum(p["usd"] for p in payments_by_person.values())
    data["payments_by_person"] = payments_by_person
    data["total_usd_received"] = total_usd_received

    # PAYOUTS: group by partner
    payouts_ledger = get_ledger("owner", "POT")
    payouts = [e for e in payouts_ledger if e.get("entry_type") in ("payout", "payment_sent") and _between(e["date"], start, end)]
    payouts_by_partner = defaultdict(lambda: {"local": 0.0, "usd": 0.0, "currency": "USD"})
    for p in payouts:
        partner_id = p.get("note", "").split(" ")[0] if p.get("note") else None
        usd_amt = abs(p.get("usd_amt", 0.0) or p.get("amount", 0.0))
        local_amt = abs(p.get("amount", 0.0))
        cur = p.get("currency", "USD")
        payouts_by_partner[partner_id]["usd"] += usd_amt
        payouts_by_partner[partner_id]["local"] += local_amt
        payouts_by_partner[partner_id]["currency"] = cur
    total_usd_paid = sum(p["usd"] for p in payouts_by_partner.values())
    data["payouts_by_partner"] = payouts_by_partner
    data["total_usd_paid"] = total_usd_paid

    # INVENTORY: per item, including unreconciled
    inventory_by_item = defaultdict(lambda: {"units": 0, "market": 0.0})
    unreconciled = {}
    store_inventory = secure_db.table("store_inventory").all()
    all_items = set(i["item_id"] for i in store_inventory)
    # market price per item (last sale)
    last_prices = {}
    for item_id in all_items:
        ledger_sales = [s for s in all_sales if s.get("item_id") == item_id]
        if ledger_sales:
            last_price = ledger_sales[-1].get("unit_price", ledger_sales[-1].get("unit_cost", 0))
        else:
            last_price = store_inventory[0].get("unit_cost", 0) if store_inventory else 0
        last_prices[item_id] = last_price

    for item in store_inventory:
        item_id = item["item_id"]
        qty = item["quantity"]
        market_val = qty * last_prices.get(item_id, 0)
        inventory_by_item[item_id]["units"] += qty
        inventory_by_item[item_id]["market"] += market_val

    # Recompute inventory from ledger for reconciliation
    ledger_inv_by_item = defaultdict(float)
    # store stockins
    for store in all_stores:
        sledger = get_ledger("store", store.doc_id)
        for e in sledger:
            if e.get("entry_type") == "stockin" and _between(e.get("date", ""), start, end):
                ledger_inv_by_item[e.get("item_id")] += e.get("quantity", 0)
    # partner stockins
    for partner in secure_db.all("partners"):
        pledger = get_ledger("partner", partner.doc_id)
        for e in pledger:
            if e.get("entry_type") == "stockin" and _between(e.get("date", ""), start, end):
                ledger_inv_by_item[e.get("item_id")] += e.get("quantity", 0)
    # sales
    for sale in all_sales:
        ledger_inv_by_item[sale.get("item_id")] -= abs(sale.get("quantity", 0))

    # Identify unreconciled inventory
    for item_id in set(list(inventory_by_item.keys()) + list(ledger_inv_by_item.keys())):
        actual = inventory_by_item[item_id]["units"]
        expected = ledger_inv_by_item.get(item_id, 0)
        if abs(actual - expected) > 0.01:
            unreconciled[item_id] = {
                "units": actual - expected,
                "market": (actual - expected) * last_prices.get(item_id, 0)
            }
    data["inventory_by_item"] = inventory_by_item
    data["unreconciled"] = unreconciled

    # EXPENSES
    all_expenses = [e for e in pot_ledger if e.get("entry_type") in ("expense", "fee") and _between(e.get("date"), start, end)]
    total_expenses = sum(abs(e.get("amount", 0)) for e in all_expenses)
    data["expenses"] = all_expenses
    data["total_expenses"] = total_expenses

    # FINANCIAL POSITION
    net_position = pot_balance + sum(i["market"] for i in inventory_by_item.values())
    data["net_position"] = net_position

    return data

# ... [THE REST OF THE FILE IS THE SAME AS THE OWNER REPORT HANDLER ABOVE: _render_page, _build_pdf, handlers, etc.]
# (For brevity, you can use the previous version's Telegram handler, PDF builder, and handler registration code here.)
