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

def get_last_sale_price_any(sales, stockins, item_id):
    relevant_sales = [e for e in sales if e.get("item_id") == item_id]
    if relevant_sales:
        latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 0))
    else:
        relevant_stockins = [e for e in stockins if e.get("item_id") == item_id]
        if relevant_stockins:
            latest = sorted(relevant_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
            return latest.get("unit_cost", 0)
    return 0

def compute_inventory(secure_db, get_ledger, start=None, end=None):
    inventory_by_item = defaultdict(lambda: {"units": 0, "market": 0.0})
    all_sales = []
    all_stockins = []
    # Stockins from stores
    for store in secure_db.all("stores"):
        sledger = get_ledger("store", store.doc_id)
        for e in sledger:
            if e.get("entry_type") == "stockin" and ((not start) or _between(e.get("date", ""), start, end)):
                item_id = e.get("item_id")
                qty = e.get("quantity", 0)
                inventory_by_item[item_id]["units"] += qty
                all_stockins.append(e)
    # Stockins from partners
    for partner in secure_db.all("partners"):
        pledger = get_ledger("partner", partner.doc_id)
        for e in pledger:
            if e.get("entry_type") == "stockin" and ((not start) or _between(e.get("date", ""), start, end)):
                item_id = e.get("item_id")
                qty = e.get("quantity", 0)
                inventory_by_item[item_id]["units"] += qty
                all_stockins.append(e)
    # Sales from customers
    for c in secure_db.all("customers"):
        cust_ledger = get_ledger("customer", c.doc_id)
        for e in cust_ledger:
            if e.get("entry_type") == "sale" and ((not start) or _between(e.get("date", ""), start, end)):
                item_id = e.get("item_id")
                qty = abs(e.get("quantity", 0))
                inventory_by_item[item_id]["units"] -= qty
                all_sales.append(e)
    # Sales from general ledger
    general_ledger = get_ledger("general", None)
    for e in general_ledger:
        if e.get("entry_type") == "sale" and ((not start) or _between(e.get("date", ""), start, end)):
            item_id = e.get("item_id")
            qty = abs(e.get("quantity", 0))
            inventory_by_item[item_id]["units"] -= qty
            all_sales.append(e)
    # Market value for each item
    for item_id in inventory_by_item.keys():
        price = get_last_sale_price_any(all_sales, all_stockins, item_id)
        inventory_by_item[item_id]["market"] = inventory_by_item[item_id]["units"] * price
    return inventory_by_item, all_sales, all_stockins

def compute_store_and_owner_inventory(secure_db, get_ledger):
    store_inventory = defaultdict(lambda: defaultdict(lambda: {"units": 0, "market": 0.0}))
    owner_totals = defaultdict(lambda: {"units": 0, "market": 0.0})
    all_sales = []
    all_stockins = []

    for store in secure_db.all("stores"):
        sledger = get_ledger("store", store.doc_id)
        for e in sledger:
            if e.get("entry_type") == "stockin":
                item_id = e.get("item_id")
                qty = e.get("quantity", 0)
                store_inventory[store.doc_id][item_id]["units"] += qty
                all_stockins.append(e)

    for customer in secure_db.all("customers"):
        cledger = get_ledger("customer", customer.doc_id)
        for e in cledger:
            if e.get("entry_type") == "sale":
                store_id = e.get("store_id")
                item_id = e.get("item_id")
                qty = abs(e.get("quantity", 0))
                store_inventory[store_id][item_id]["units"] -= qty
                all_sales.append(e)

    general_ledger = get_ledger("general", None)
    for e in general_ledger:
        if e.get("entry_type") == "sale":
            store_id = e.get("store_id")
            item_id = e.get("item_id")
            qty = abs(e.get("quantity", 0))
            store_inventory[store_id][item_id]["units"] -= qty
            all_sales.append(e)

    def get_last_price(item_id):
        relevant_sales = [e for e in all_sales if e.get("item_id") == item_id]
        if relevant_sales:
            latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
            return latest.get("unit_price", latest.get("unit_cost", 0))
        relevant_stockins = [e for e in all_stockins if e.get("item_id") == item_id]
        if relevant_stockins:
            latest = sorted(relevant_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
            return latest.get("unit_cost", 0)
        return 0

    for store_id, items in store_inventory.items():
        for item_id, v in items.items():
            price = get_last_price(item_id)
            v["market"] = v["units"] * price
            owner_totals[item_id]["units"] += v["units"]
            owner_totals[item_id]["market"] += v["market"]

    return store_inventory, owner_totals

def debug_dump_payouts(secure_db, get_ledger, start, end):
    print("\n[DEBUG] OWNER POT LEDGER PAYOUT ENTRIES:")
    pot_ledger = get_ledger("owner", "POT")
    for e in pot_ledger:
        if e.get("entry_type") in ("payout", "payment_sent") and _between(e["date"], start, end):
            partner_id = e.get("related_id")
            partner_name = None
            if partner_id:
                try:
                    partner = secure_db.table("partners").get(doc_id=int(partner_id))
                    partner_name = partner.get("name") if partner else None
                except Exception:
                    partner_name = None
            print(f"- Date: {e.get('date')}, Amount: {e.get('usd_amt', e.get('amount'))} USD, "
                  f"PartnerID: {partner_id}, PartnerName: {partner_name}, Raw: {e}")

    print("\n[DEBUG] ALL PARTNER LEDGER PAYOUT RECEIVED ENTRIES:")
    for partner in secure_db.all("partners"):
        pledger = get_ledger("partner", partner.doc_id)
        for e in pledger:
            if "payout" in e.get("entry_type", ""):
                print(f"- Date: {e.get('date')}, Amount: {e.get('usd_amt', e.get('amount'))} USD, "
                      f"PartnerName: {partner.get('name')}, Raw: {e}")
    print("---- END OF DEBUG DUMP ----")

def cross_check_payouts(secure_db, get_ledger, start, end):
    pot_ledger = get_ledger("owner", "POT")
    payout_entries = [
        e for e in pot_ledger
        if e.get("entry_type") in ("payout", "payment_sent") and _between(e["date"], start, end)
    ]
    print("\nPAYOUT CROSS-CHECK:")
    for payout in payout_entries:
        partner_id = payout.get("related_id")
        usd_amt = abs(payout.get("usd_amt", payout.get("amount", 0)))
        partner_name = None
        if partner_id:
            try:
                partner = secure_db.table("partners").get(doc_id=int(partner_id))
            except Exception:
                partner = None
            if partner:
                partner_name = partner.get("name")
                # Search partner's ledger for a matching payout-in
                pledger = get_ledger("partner", int(partner_id))
                match = [
                    e for e in pledger
                    if abs(e.get("usd_amt", e.get("amount", 0))) == usd_amt
                    and e.get("entry_type", "").startswith("payout")
                    and _between(e["date"], start, end)
                ]
                if match:
                    print(f"  ✔️ Payout to partner {partner_name} (${usd_amt}) FOUND in partner ledger.")
                else:
                    print(f"  ⚠️ Payout to partner {partner_name} (${usd_amt}) NOT FOUND in partner ledger!")
            else:
                print(f"  ⚠️ Payout related_id {partner_id} not found in partners table.")
        else:
            print(f"  ⚠️ Payout entry without related_id: {payout}")

def owner_report_diagnostic(start, end, secure_db, get_ledger):
    debug_dump_payouts(secure_db, get_ledger, start, end)
    print("\n==== OWNER REPORT DIAGNOSTIC ====")
    print(f"DATE RANGE: {fmt_date(start.strftime('%d%m%Y'))} to {fmt_date(end.strftime('%d%m%Y'))}")

    pot_ledger = get_ledger("owner", "POT")
    print(f"\n[Owner POT ledger] {len(pot_ledger)} entries in ledger.")

    payments = [e for e in pot_ledger if e.get("entry_type") == "payment_recv" and _between(e["date"], start, end)]
    currency_groups = defaultdict(lambda: {"local": 0.0, "usd": 0.0, "currency": "USD"})
    for p in payments:
        cur = p.get("currency", "USD")
        currency_groups[cur]["local"] += p.get("amount", 0.0)
        currency_groups[cur]["usd"] += p.get("usd_amt", 0.0)
        currency_groups[cur]["currency"] = cur
    print(f"\nPayments Received ({len(payments)} entries):")
    for cur, group in currency_groups.items():
        print(f"  {cur}: {group['local']} {cur} | {group['usd']} USD")
    print(f"  > Total USD Received: {sum(group['usd'] for group in currency_groups.values())}")

    payouts = [e for e in pot_ledger if e.get("entry_type") in ("payout", "payment_sent") and _between(e["date"], start, end)]
    print(f"\nPayouts ({len(payouts)} entries):")
    print(f"  > Total USD Paid Out: {sum(abs(e.get('usd_amt', e.get('amount', 0.0))) for e in payouts)}")

    expenses = [e for e in pot_ledger if e.get("entry_type") in ("expense", "fee") and _between(e.get("date"), start, end)]
    print(f"\nExpenses ({len(expenses)} entries):")
    print(f"  > Total Expenses: {sum(abs(e.get('amount', 0)) for e in expenses)}")

    all_sales = []
    for cust in secure_db.all("customers"):
        cust_ledger = get_ledger("customer", cust.doc_id)
        for e in cust_ledger:
            if e.get("entry_type") == "sale" and _between(e.get("date", ""), start, end):
                all_sales.append(e)
    general_ledger = get_ledger("general", None)
    for e in general_ledger:
        if e.get("entry_type") == "sale" and _between(e.get("date", ""), start, end):
            all_sales.append(e)
    print(f"\nSales entries in range: {len(all_sales)}")

    inv_period, _, _ = compute_inventory(secure_db, get_ledger, start, end)
    print("\nInventory by item (period):")
    for item_id, v in inv_period.items():
        print(f"  {item_id}: {v['units']} units, ${v['market']}")

    inv_all, _, _ = compute_inventory(secure_db, get_ledger, None, None)
    print("\nInventory by item (all time):")
    for item_id, v in inv_all.items():
        print(f"  {item_id}: {v['units']} units, ${v['market']}")
    cross_check_payouts(secure_db, get_ledger, start, end)
    print("==== END OWNER REPORT DIAGNOSTIC ====\n")

def _reset_state(ctx):
    for k in ("start_date", "end_date", "page", "scope", "report_data"):
        ctx.user_data.pop(k, None)

def _paginate(lst, page):
    start = page * _PAGE_SIZE
    return lst[start : start + _PAGE_SIZE]

def _collect_report_data(start, end):
    data = {}
    pot_ledger = get_ledger("owner", "POT")

    pot_in = sum(e["amount"] for e in pot_ledger if e.get("entry_type") == "payment_recv" and _between(e["date"], start, end))
    pot_out = sum(e["amount"] for e in pot_ledger if e.get("entry_type") in ("payout", "payment_sent") and _between(e["date"], start, end))
    pot_balance = sum(e["amount"] for e in pot_ledger)
    net_change = pot_in + pot_out

    data["pot"] = {
        "balance": pot_balance,
        "inflows": pot_in,
        "outflows": abs(pot_out),
        "net": net_change,
    }

    sales_by_store_item = defaultdict(lambda: defaultdict(lambda: {"units": 0, "value": 0.0}))
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
    general_ledger = get_ledger("general", None)
    for e in general_ledger:
        if e.get("entry_type") == "sale" and _between(e.get("date", ""), start, end):
            store_id = e.get("store_id")
            item_id = e.get("item_id")
            qty = abs(e.get("quantity", 0))
            value = abs(qty * e.get("unit_price", e.get("unit_cost", 0)))
            sales_by_store_item[store_id][item_id]["units"] += qty
            sales_by_store_item[store_id][item_id]["value"] += value
    data["sales_by_store_item"] = sales_by_store_item

    # -- NEW: PAYMENTS RECEIVED FROM ALL CUSTOMER LEDGERS --
    payments_by_currency = defaultdict(lambda: {"local": 0.0, "usd": 0.0, "currency": ""})
    for customer in secure_db.all("customers"):
        cledger = get_ledger("customer", customer.doc_id)
        for e in cledger:
            if e.get("entry_type") == "payment" and _between(e.get("date", ""), start, end):
                cur = e.get("currency", "USD")
                amt = e.get("amount", 0.0)
                usd = e.get("usd_amt", 0.0)
                payments_by_currency[cur]["local"] += amt
                payments_by_currency[cur]["usd"] += usd
                payments_by_currency[cur]["currency"] = cur
    total_usd_received = sum(grp["usd"] for grp in payments_by_currency.values())
    data["payments_by_currency"] = payments_by_currency
    data["total_usd_received"] = total_usd_received

    payouts = [e for e in pot_ledger if e.get("entry_type") in ("payout", "payment_sent") and _between(e["date"], start, end)]
    total_usd_paid = sum(abs(e.get("usd_amt", e.get("amount", 0.0))) for e in payouts)
    data["total_usd_paid"] = total_usd_paid

    inventory_by_item, all_sales_period, all_stockins_period = compute_inventory(secure_db, get_ledger, start, end)
    data["inventory_by_item"] = inventory_by_item

    inventory_by_item_all, _, _ = compute_inventory(secure_db, get_ledger, None, None)
    data["current_inventory_all_time"] = inventory_by_item_all

    store_inventory, owner_totals = compute_store_and_owner_inventory(secure_db, get_ledger)
    data["store_inventory_by_item"] = store_inventory
    data["owner_inventory_totals"] = owner_totals

    unreconciled = {}
    store_inventory_table = secure_db.table("store_inventory").all()
    inv_actual_by_item = defaultdict(float)
    for item in store_inventory_table:
        inv_actual_by_item[item['item_id']] += item['quantity']
    for item_id in set(list(inv_actual_by_item.keys()) + list(inventory_by_item.keys())):
        actual = inv_actual_by_item.get(item_id, 0)
        expected = inventory_by_item.get(item_id, {}).get("units", 0)
        if abs(actual - expected) > 0.01:
            unreconciled[item_id] = {
                "units": actual - expected,
                "market": (actual - expected) * get_last_sale_price_any([], [], item_id)
            }
    data["unreconciled"] = unreconciled

    all_expenses = [e for e in pot_ledger if e.get("entry_type") in ("expense", "fee") and _between(e.get("date"), start, end)]
    total_expenses = sum(abs(e.get("amount", 0)) for e in all_expenses)
    data["expenses"] = all_expenses
    data["total_expenses"] = total_expenses

    net_position = pot_balance + sum(i["market"] for i in inventory_by_item_all.values())
    data["net_position"] = net_position

    owner_report_diagnostic(start, end, secure_db, get_ledger)

    return data

def _render_page(ctx):
    data = ctx["report_data"]
    page = ctx.get("page", 0)
    pages = []

    if page == 0:
        lines = []
        lines.append("👑 OWNER SUMMARY OVERVIEW")
        lines.append(f"Date Range: {fmt_date(ctx['start_date'].strftime('%d%m%Y'))} – {fmt_date(ctx['end_date'].strftime('%d%m%Y'))}\n")
        pot = data["pot"]
        lines.append("─────────────────────────────\n💲 POT (USD Account)")
        lines.append(f"  Balance: {fmt_money(pot['balance'], 'USD')}")
        lines.append(f"  Inflows: {fmt_money(pot['inflows'], 'USD')}")
        lines.append(f"  Outflows: {fmt_money(pot['outflows'], 'USD')}")
        lines.append(f"  Net Change: {fmt_money(pot['net'], 'USD')}\n")
        lines.append("🛒 SALES (by item)")
        if any(data["sales_by_store_item"].values()):
            for store_id, items in data["sales_by_store_item"].items():
                store = secure_db.table("stores").get(doc_id=store_id) or {"name": f"Store {store_id}"}
                for item_id, v in items.items():
                    lines.append(f"  - {store['name']}: {v['units']} units [item {item_id}] | {fmt_money(v['value'], 'USD')}")
        else:
            lines.append("  No sales in this period.")
        pages.append("\n".join(lines))

    if page == 1:
        lines = []
        lines.append("─────────────────────────────\n💰 PAYMENTS RECEIVED")
        if data["payments_by_currency"]:
            for cur, group in data["payments_by_currency"].items():
                lines.append(f"{cur}: {fmt_money(group['local'], cur)} | {fmt_money(group['usd'], 'USD')}")
            lines.append(f"\nTotal USD Received (all currencies): {fmt_money(data['total_usd_received'], 'USD')}")
        else:
            lines.append("No payments received in this period.")
            lines.append(f"\nTotal USD Received (all currencies): $0.00")
        pages.append("\n".join(lines))
    if page == 2:
        lines = []
        lines.append("─────────────────────────────\n💸 PAYOUTS TO PARTNERS")
        lines.append(f"  Total USD Paid Out: {fmt_money(data['total_usd_paid'], 'USD')}")
        if data["total_usd_paid"] == 0:
            lines.append("  (No payouts this period.)")
        else:
            lines.append("  (Payouts are cross-checked in diagnostics log.)")
        pages.append("\n".join(lines))
    if page == 3:
        lines = []
        lines.append("─────────────────────────────\n📦 INVENTORY (for period)")
        if data["inventory_by_item"]:
            for item_id, v in data["inventory_by_item"].items():
                lines.append(f"  {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}")
            lines.append(f"  Total Inventory Value: {fmt_money(sum(v['market'] for v in data['inventory_by_item'].values()), 'USD')}")
        else:
            lines.append("  No inventory movements in this period.")
            lines.append("  Total Inventory Value: $0.00")
        if data["unreconciled"]:
            lines.append("\n⚠️ UNRECONCILED INVENTORY")
            for item_id, v in data["unreconciled"].items():
                lines.append(f"  - {item_id}: {v['units']} units ({fmt_money(v['market'], 'USD')})")
        lines.append("\n📦 CURRENT INVENTORY (ALL TIME)")
        if data["current_inventory_all_time"]:
            for item_id, v in data["current_inventory_all_time"].items():
                lines.append(f"  {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}")
            lines.append(f"  Total Inventory Value (all time): {fmt_money(sum(v['market'] for v in data['current_inventory_all_time'].values()), 'USD')}")
        else:
            lines.append("  No inventory on hand (all time).")
            lines.append("  Total Inventory Value (all time): $0.00")
        pages.append("\n".join(lines))
    if page == 4:
        lines = []
        lines.append("─────────────────────────────\n📉 EXPENSES")
        if data["expenses"]:
            for e in data["expenses"]:
                lines.append(f"  {fmt_date(e['date'])}: {fmt_money(abs(e['amount']), e['currency'])}")
            lines.append(f"  Total Expenses: {fmt_money(data['total_expenses'], 'USD')}")
        else:
            lines.append("No expenses in this period.")
            lines.append(f"  Total Expenses: $0.00")
        pages.append("\n".join(lines))
    if page == 5:
        lines = []
        lines.append("─────────────────────────────\n🏁 FINANCIAL POSITION (USD)")
        pot = data["pot"]
        inventory_value = sum(v["market"] for v in data["current_inventory_all_time"].values())
        lines.append(f"  POT Balance: {fmt_money(pot['balance'], 'USD')}")
        lines.append(f"  + Inventory: {fmt_money(inventory_value, 'USD')}")
        lines.append(f"  = NET POSITION: {fmt_money(data['net_position'], 'USD')}")
        pages.append("\n".join(lines))

    # NEW INVENTORY BY STORE AND TYPE PAGE
    if page == 6:
        lines = []
        lines.append("─────────────────────────────\n📦 INVENTORY ON HAND (by Store and Type)")
        store_inventory = data.get("store_inventory_by_item", {})
        owner_totals = data.get("owner_inventory_totals", {})
        if store_inventory:
            for store_id, items in store_inventory.items():
                store = secure_db.table("stores").get(doc_id=store_id) or {"name": f"Store {store_id}"}
                for item_id, v in items.items():
                    lines.append(f"{store['name']} | Item {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}")
        else:
            lines.append("No inventory on hand in any store.")
        lines.append("\nOWNER TOTALS BY ITEM:")
        if owner_totals:
            for item_id, v in owner_totals.items():
                lines.append(f"Item {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}")
        else:
            lines.append("No inventory on hand for any item.")
        pages.append("\n".join(lines))

    return pages

# ... rest of your file (PDF export, handlers, etc) unchanged ...
def _build_pdf(ctx):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 36
    p.setFont("Helvetica", 12)

    data = ctx["report_data"]

    def write(line, y):
        p.drawString(40, y, line)
        return y - 18

    y = write("👑 OWNER SUMMARY OVERVIEW", y)
    y = write(f"Date Range: {fmt_date(ctx['start_date'].strftime('%d%m%Y'))} – {fmt_date(ctx['end_date'].strftime('%d%m%Y'))}", y)
    y -= 10

    pot = data["pot"]
    y = write("💲 POT (USD Account)", y)
    y = write(f"  Balance: {fmt_money(pot['balance'], 'USD')}", y)
    y = write(f"  Inflows: {fmt_money(pot['inflows'], 'USD')}", y)
    y = write(f"  Outflows: {fmt_money(pot['outflows'], 'USD')}", y)
    y = write(f"  Net Change: {fmt_money(pot['net'], 'USD')}", y)
    y -= 10

    y = write("🛒 SALES (by item)", y)
    if any(data["sales_by_store_item"].values()):
        for store_id, items in data["sales_by_store_item"].items():
            store = secure_db.table("stores").get(doc_id=store_id) or {"name": f"Store {store_id}"}
            for item_id, v in items.items():
                y = write(f"  - {store['name']}: {v['units']} units [item {item_id}] | {fmt_money(v['value'], 'USD')}", y)
    else:
        y = write("  No sales in this period.", y)
    y -= 10

    y = write("💰 PAYMENTS RECEIVED", y)
    if data["payments_by_currency"]:
        for cur, group in data["payments_by_currency"].items():
            y = write(f"{cur}: {fmt_money(group['local'], cur)} | {fmt_money(group['usd'], 'USD')}", y)
        y = write(f"\nTotal USD Received (all currencies): {fmt_money(data['total_usd_received'], 'USD')}", y)
    else:
        y = write("No payments received in this period.", y)
        y = write(f"\nTotal USD Received (all currencies): $0.00", y)
    y -= 10

    y = write("💸 PAYOUTS TO PARTNERS", y)
    y = write(f"  Total USD Paid Out: {fmt_money(data['total_usd_paid'], 'USD')}", y)
    if data["total_usd_paid"] == 0:
        y = write("  (No payouts this period.)", y)
    else:
        y = write("  (Payouts are cross-checked in diagnostics log.)", y)
    y -= 10

    y = write("📦 INVENTORY (for period)", y)
    if data["inventory_by_item"]:
        for item_id, v in data["inventory_by_item"].items():
            y = write(f"  {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}", y)
        y = write(f"  Total Inventory Value: {fmt_money(sum(v['market'] for v in data['inventory_by_item'].values()), 'USD')}", y)
    else:
        y = write("  No inventory movements in this period.", y)
        y = write("  Total Inventory Value: $0.00", y)
    if data["unreconciled"]:
        y -= 10
        y = write("⚠️ UNRECONCILED INVENTORY", y)
        for item_id, v in data["unreconciled"].items():
            y = write(f"  - {item_id}: {v['units']} units ({fmt_money(v['market'], 'USD')})", y)
    y = write("📦 CURRENT INVENTORY (ALL TIME)", y)
    if data["current_inventory_all_time"]:
        for item_id, v in data["current_inventory_all_time"].items():
            y = write(f"  {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}", y)
        y = write(f"  Total Inventory Value (all time): {fmt_money(sum(v['market'] for v in data['current_inventory_all_time'].values()), 'USD')}", y)
    else:
        y = write("  No inventory on hand (all time).", y)
        y = write("  Total Inventory Value (all time): $0.00", y)
    y -= 10

    y = write("📦 INVENTORY ON HAND (by Store and Type)", y)
    store_inventory = data.get("store_inventory_by_item", {})
    owner_totals = data.get("owner_inventory_totals", {})
    if store_inventory:
        for store_id, items in store_inventory.items():
            store = secure_db.table("stores").get(doc_id=store_id) or {"name": f"Store {store_id}"}
            for item_id, v in items.items():
                y = write(f"{store['name']} | Item {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}", y)
    else:
        y = write("No inventory on hand in any store.", y)
    y = write("OWNER TOTALS BY ITEM:", y)
    if owner_totals:
        for item_id, v in owner_totals.items():
            y = write(f"Item {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}", y)
    else:
        y = write("No inventory on hand for any item.", y)
    y -= 10

    y = write("📉 EXPENSES", y)
    if data["expenses"]:
        for e in data["expenses"]:
            y = write(f"  {fmt_date(e['date'])}: {fmt_money(abs(e['amount']), e['currency'])}", y)
        y = write(f"  Total Expenses: {fmt_money(data['total_expenses'], 'USD')}", y)
    else:
        y = write("No expenses in this period.", y)
        y = write(f"  Total Expenses: $0.00", y)
    y -= 10

    y = write("🏁 FINANCIAL POSITION (USD)", y)
    inventory_value = sum(v["market"] for v in data["current_inventory_all_time"].values())
    y = write(f"  POT Balance: {fmt_money(pot['balance'], 'USD')}", y)
    y = write(f"  + Inventory: {fmt_money(inventory_value, 'USD')}", y)
    y = write(f"  = NET POSITION: {fmt_money(data['net_position'], 'USD')}", y)
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

@require_unlock
async def show_owner_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_state(context)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 7 days", callback_data="owner_range_week")],
        [InlineKeyboardButton("📆 Custom Range", callback_data="owner_range_custom")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return OWNER_DATE_RANGE_SELECT

async def owner_custom_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Enter start date DDMMYYYY:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
    )
    return OWNER_CUSTOM_DATE_INPUT

async def owner_save_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    try:
        sd = datetime.strptime(txt, "%d%m%Y")
    except ValueError:
        await update.message.reply_text("❌ Format DDMMYYYY please.")
        return OWNER_CUSTOM_DATE_INPUT
    context.user_data["start_date"] = sd
    context.user_data["end_date"] = datetime.now()
    context.user_data["page"] = 0
    context.user_data["report_data"] = _collect_report_data(sd, datetime.now())
    return await owner_show_report(update, context)

async def owner_choose_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == "owner_range_week":
        context.user_data["start_date"] = datetime.now() - timedelta(days=7)
        context.user_data["end_date"] = datetime.now()
    elif update.callback_query.data == "owner_range_custom":
        return await owner_custom_date_input(update, context)
    context.user_data["page"] = 0
    context.user_data["report_data"] = _collect_report_data(context.user_data["start_date"], context.user_data["end_date"])
    return await owner_show_report(update, context)

@require_unlock
async def owner_show_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ctx = context.user_data
    pages = []
    for i in range(7):  # 7 pages/sections
        ctx_page_backup = ctx.get("page", 0)
        ctx["page"] = i
        section = _render_page(ctx)
        if section:
            pages.append(section[0])
        ctx["page"] = ctx_page_backup

    page = ctx.get("page", 0)

    kb = []
    if page > 0:
        kb.append(InlineKeyboardButton("⬅️ Prev", callback_data="owner_page_prev"))
    if page < len(pages) - 1:
        kb.append(InlineKeyboardButton("➡️ Next", callback_data="owner_page_next"))
    kb.append(InlineKeyboardButton("📄 Export PDF", callback_data="owner_export_pdf"))
    kb.append(InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))

    await update.callback_query.edit_message_text(
        pages[page],
        reply_markup=InlineKeyboardMarkup([kb]),
        parse_mode="Markdown"
    )
    return OWNER_REPORT_PAGE

@require_unlock
async def owner_paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == "owner_page_next":
        context.user_data["page"] += 1
    elif update.callback_query.data == "owner_page_prev":
        context.user_data["page"] = max(0, context.user_data["page"] - 1)
    return await owner_show_report(update, context)

@require_unlock
async def owner_export_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Generating PDF …")
    ctx = context.user_data
    pdf_buf = _build_pdf(ctx)
    pdf_file = InputFile(pdf_buf, filename=f"Owner_Summary_{datetime.now().strftime('%Y%m%d')}.pdf")
    await update.callback_query.message.reply_document(pdf_file, caption="Owner Summary PDF")
    return await owner_show_report(update, context)

def register_owner_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_owner_report_menu, pattern="^rep_owner$"))
    app.add_handler(CallbackQueryHandler(owner_choose_scope, pattern="^owner_range_"))
    app.add_handler(CallbackQueryHandler(owner_paginate, pattern="^owner_page_"))
    app.add_handler(CallbackQueryHandler(owner_export_pdf, pattern="^owner_export_pdf$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: None, pattern="^main_menu$"))
    app.add_handler(MessageHandler(None, owner_save_custom_start))
