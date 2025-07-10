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

def get_last_sale_price(sales, stockins, item_id):
    relevant_sales = [e for e in sales if e.get("item_id") == item_id]
    if relevant_sales:
        # Get latest sale price
        latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 0))
    else:
        # Fallback to latest stock-in cost if no sale
        relevant_stockins = [e for e in stockins if e.get("item_id") == item_id]
        if relevant_stockins:
            latest = sorted(relevant_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
            return latest.get("unit_cost", 0)
    return 0

def _collect_report_data(start, end):
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

    # LEDGER-BASED INVENTORY CALCULATION
    ledger_inventory = defaultdict(lambda: {"units": 0, "market": 0.0})
    all_stockins = []
    for store in all_stores:
        sledger = get_ledger("store", store.doc_id)
        for e in sledger:
            if e.get("entry_type") == "stockin":
                item_id = e.get("item_id")
                qty = e.get("quantity", 0)
                ledger_inventory[item_id]["units"] += qty
                all_stockins.append(e)
    for partner in secure_db.all("partners"):
        pledger = get_ledger("partner", partner.doc_id)
        for e in pledger:
            if e.get("entry_type") == "stockin":
                item_id = e.get("item_id")
                qty = e.get("quantity", 0)
                ledger_inventory[item_id]["units"] += qty
                all_stockins.append(e)
    for c in all_customers:
        cust_ledger = get_ledger("customer", c.doc_id)
        for e in cust_ledger:
            if e.get("entry_type") == "sale":
                item_id = e.get("item_id")
                qty = abs(e.get("quantity", 0))
                ledger_inventory[item_id]["units"] -= qty

    # Market value per item (using last sale price or last stock-in cost)
    for item_id in ledger_inventory.keys():
        price = get_last_sale_price(all_sales, all_stockins, item_id)
        ledger_inventory[item_id]["market"] = ledger_inventory[item_id]["units"] * price
    data["inventory_by_item"] = ledger_inventory

    # For audit only: unreconciled inventory (difference from store_inventory)
    unreconciled = {}
    store_inventory = secure_db.table("store_inventory").all()
    inv_actual_by_item = defaultdict(float)
    for item in store_inventory:
        inv_actual_by_item[item['item_id']] += item['quantity']
    for item_id in set(list(inv_actual_by_item.keys()) + list(ledger_inventory.keys())):
        actual = inv_actual_by_item.get(item_id, 0)
        expected = ledger_inventory.get(item_id, {}).get("units", 0)
        if abs(actual - expected) > 0.01:
            unreconciled[item_id] = {
                "units": actual - expected,
                "market": (actual - expected) * get_last_sale_price(all_sales, all_stockins, item_id)
            }
    data["unreconciled"] = unreconciled

    # EXPENSES
    all_expenses = [e for e in pot_ledger if e.get("entry_type") in ("expense", "fee") and _between(e.get("date"), start, end)]
    total_expenses = sum(abs(e.get("amount", 0)) for e in all_expenses)
    data["expenses"] = all_expenses
    data["total_expenses"] = total_expenses

    # FINANCIAL POSITION
    net_position = pot_balance + sum(i["market"] for i in ledger_inventory.values())
    data["net_position"] = net_position

    # Diagnostic print (shows all source data)
    owner_report_diagnostic(start, end, secure_db, get_ledger, ledger_inventory)

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
        for store_id, items in data["sales_by_store_item"].items():
            store = secure_db.table("stores").get(doc_id=store_id) or {"name": f"Store {store_id}"}
            for item_id, v in items.items():
                lines.append(f"  - {store['name']}: {v['units']} units [item {item_id}] | {fmt_money(v['value'], 'USD')}")
        pages.append("\n".join(lines))

    if page == 1:
        lines = []
        lines.append("─────────────────────────────\n💰 PAYMENTS RECEIVED")
        for name, v in data["payments_by_person"].items():
            if name:
                lines.append(f"  {name}: {fmt_money(v['local'], v['currency'])} | {fmt_money(v['usd'], 'USD')}")
        lines.append(f"  Total USD Received: {fmt_money(data['total_usd_received'], 'USD')}")
        pages.append("\n".join(lines))
    if page == 2:
        lines = []
        lines.append("─────────────────────────────\n💸 PAYOUTS TO PARTNERS")
        for name, v in data["payouts_by_partner"].items():
            if name:
                lines.append(f"  {name}: {fmt_money(v['local'], v['currency'])} | {fmt_money(v['usd'], 'USD')}")
        lines.append(f"  Total USD Paid Out: {fmt_money(data['total_usd_paid'], 'USD')}")
        pages.append("\n".join(lines))
    if page == 3:
        lines = []
        lines.append("─────────────────────────────\n📦 INVENTORY")
        for item_id, v in data["inventory_by_item"].items():
            lines.append(f"  {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}")
        lines.append(f"  Total Inventory Value: {fmt_money(sum(v['market'] for v in data['inventory_by_item'].values()), 'USD')}")
        if data["unreconciled"]:
            lines.append("\n⚠️ UNRECONCILED INVENTORY")
            for item_id, v in data["unreconciled"].items():
                lines.append(f"  - {item_id}: {v['units']} units ({fmt_money(v['market'], 'USD')})")
        pages.append("\n".join(lines))
    if page == 4:
        lines = []
        lines.append("─────────────────────────────\n📉 EXPENSES")
        for e in data["expenses"]:
            lines.append(f"  {fmt_date(e['date'])}: {fmt_money(abs(e['amount']), e['currency'])}")
        lines.append(f"  Total Expenses: {fmt_money(data['total_expenses'], 'USD')}")
        pages.append("\n".join(lines))
    if page == 5:
        lines = []
        lines.append("─────────────────────────────\n🏁 FINANCIAL POSITION (USD)")
        pot = data["pot"]
        inventory_value = sum(v["market"] for v in data["inventory_by_item"].values())
        lines.append(f"  POT Balance: {fmt_money(pot['balance'], 'USD')}")
        lines.append(f"  + Inventory: {fmt_money(inventory_value, 'USD')}")
        lines.append(f"  = NET POSITION: {fmt_money(data['net_position'], 'USD')}")
        pages.append("\n".join(lines))
    return pages

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

    # POT
    pot = data["pot"]
    y = write("💲 POT (USD Account)", y)
    y = write(f"  Balance: {fmt_money(pot['balance'], 'USD')}", y)
    y = write(f"  Inflows: {fmt_money(pot['inflows'], 'USD')}", y)
    y = write(f"  Outflows: {fmt_money(pot['outflows'], 'USD')}", y)
    y = write(f"  Net Change: {fmt_money(pot['net'], 'USD')}", y)
    y -= 10

    # Sales summary
    y = write("🛒 SALES (by item)", y)
    for store_id, items in data["sales_by_store_item"].items():
        store = secure_db.table("stores").get(doc_id=store_id) or {"name": f"Store {store_id}"}
        for item_id, v in items.items():
            y = write(f"  - {store['name']}: {v['units']} units [item {item_id}] | {fmt_money(v['value'], 'USD')}", y)
    y -= 10

    # Payments received
    y = write("💰 PAYMENTS RECEIVED", y)
    for name, v in data["payments_by_person"].items():
        if name:
            y = write(f"  {name}: {fmt_money(v['local'], v['currency'])} | {fmt_money(v['usd'], 'USD')}", y)
    y = write(f"  Total USD Received: {fmt_money(data['total_usd_received'], 'USD')}", y)
    y -= 10

    # Payouts
    y = write("💸 PAYOUTS TO PARTNERS", y)
    for name, v in data["payouts_by_partner"].items():
        if name:
            y = write(f"  {name}: {fmt_money(v['local'], v['currency'])} | {fmt_money(v['usd'], 'USD')}", y)
    y = write(f"  Total USD Paid Out: {fmt_money(data['total_usd_paid'], 'USD')}", y)
    y -= 10

    # Inventory
    y = write("📦 INVENTORY", y)
    for item_id, v in data["inventory_by_item"].items():
        y = write(f"  {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}", y)
    y = write(f"  Total Inventory Value: {fmt_money(sum(v['market'] for v in data['inventory_by_item'].values()), 'USD')}", y)
    if data["unreconciled"]:
        y -= 10
        y = write("⚠️ UNRECONCILED INVENTORY", y)
        for item_id, v in data["unreconciled"].items():
            y = write(f"  - {item_id}: {v['units']} units ({fmt_money(v['market'], 'USD')})", y)
    y -= 10

    # Expenses
    y = write("📉 EXPENSES", y)
    for e in data["expenses"]:
        y = write(f"  {fmt_date(e['date'])}: {fmt_money(abs(e['amount']), e['currency'])}", y)
    y = write(f"  Total Expenses: {fmt_money(data['total_expenses'], 'USD')}", y)
    y -= 10

    # Financial position
    y = write("🏁 FINANCIAL POSITION (USD)", y)
    y = write(f"  POT Balance: {fmt_money(pot['balance'], 'USD')}", y)
    inventory_value = sum(v["market"] for v in data["inventory_by_item"].values())
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
    for i in range(6):  # total number of report pages/sections
        ctx["page"] = i
        section = _render_page(ctx)
        if section:
            pages.append(section[0])
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
