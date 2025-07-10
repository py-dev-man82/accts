# handlers/reports/owner_report.py

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

_PAGE_SIZE = 2  # Each page will include 1-2 sections for readable chunks

def _reset_state(ctx):
    for k in ("start_date", "end_date", "page", "scope", "report_data"):
        ctx.user_data.pop(k, None)

def _paginate(lst, page):
    start = page * _PAGE_SIZE
    return lst[start : start + _PAGE_SIZE]

def _between(date_str, start, end):
    try:
        dt = datetime.strptime(date_str, "%d%m%Y")
    except Exception:
        return False
    return start <= dt <= end

def get_last_sale_price(ledger, item_id):
    sales = [e for e in ledger if e.get("entry_type") == "sale" and e.get("item_id") == item_id]
    if sales:
        latest = sorted(sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 0))
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
    for s in get_ledger("customer", None):
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
    payments_received = [e for e in payments_ledger if e.get("entry_type") == "payment_recv" and _between(e.get("date", ""), start, end)]
    payments_by_person = defaultdict(lambda: {"local": 0.0, "usd": 0.0, "currency": "USD"})
    for p in payments_received:
        # Find customer
        customer_id = p.get("note", "").split(" ")[0] if p.get("note") else None
        usd_amt = p.get("usd_amt", 0.0)
        local_amt = p.get("amount", 0.0)
        cur = p.get("currency", "USD")
        # For your use case, you may want to add more sophisticated matching here
        # Example assumes note = customer name, or match using customer_id if available
        payments_by_person[customer_id]["usd"] += usd_amt
        payments_by_person[customer_id]["local"] += local_amt
        payments_by_person[customer_id]["currency"] = cur
    total_usd_received = sum(p["usd"] for p in payments_by_person.values())
    data["payments_by_person"] = payments_by_person
    data["total_usd_received"] = total_usd_received

    # PAYOUTS: group by partner
    payouts_ledger = get_ledger("owner", "POT")
    payouts = [e for e in payouts_ledger if e.get("entry_type") == "payout" and _between(e.get("date", ""), start, end)]
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
    all_stockins = get_ledger("owner", "POT")  # or get all "stockin" for owner (adjust if needed)
    for item in secure_db.table("store_inventory").all():
        item_id = item["item_id"]
        qty = item["quantity"]
        # Market price
        ledger_sales = [s for s in all_sales if s.get("item_id") == item_id]
        last_price = ledger_sales[-1]["unit_price"] if ledger_sales else item.get("unit_cost", 0)
        market_val = qty * last_price
        inventory_by_item[item_id]["units"] += qty
        inventory_by_item[item_id]["market"] += market_val
        # TODO: implement actual unreconciled inventory logic from your system if needed

    # Dummy unreconciled example: (replace with your real flag detection)
    for item_id, inv in inventory_by_item.items():
        if inv["units"] < 0:  # If negative, mark as unreconciled for demo
            unreconciled[item_id] = inv

    data["inventory_by_item"] = inventory_by_item
    data["unreconciled"] = unreconciled

    # EXPENSES
    all_expenses = [e for e in pot_ledger if e.get("entry_type") in ("expense", "fee") and _between(e.get("date", ""), start, end)]
    total_expenses = sum(abs(e.get("amount", 0)) for e in all_expenses)
    data["expenses"] = all_expenses
    data["total_expenses"] = total_expenses

    # FINANCIAL POSITION
    net_position = pot_balance + sum(i["market"] for i in inventory_by_item.values())
    data["net_position"] = net_position

    return data

def _render_page(ctx):
    """Returns a list of string sections for current page"""
    data = ctx["report_data"]
    page = ctx.get("page", 0)
    pages = []

    if page == 0:
        # Header, POT, Sales
        lines = []
        lines.append("👑 OWNER SUMMARY OVERVIEW")
        lines.append(f"Date Range: {fmt_date(ctx['start_date'].strftime('%d%m%Y'))} – {fmt_date(ctx['end_date'].strftime('%d%m%Y'))}\n")
        pot = data["pot"]
        lines.append("─────────────────────────────\n💲 POT (USD Account)")
        lines.append(f"  Balance: {fmt_money(pot['balance'], 'USD')}")
        lines.append(f"  Inflows: {fmt_money(pot['inflows'], 'USD')}")
        lines.append(f"  Outflows: {fmt_money(pot['outflows'], 'USD')}")
        lines.append(f"  Net Change: {fmt_money(pot['net'], 'USD')}\n")
        # Sales summary
        lines.append("🛒 SALES (by item)")
        for store_id, items in data["sales_by_store_item"].items():
            store = secure_db.table("stores").get(doc_id=store_id) or {"name": f"Store {store_id}"}
            for item_id, v in items.items():
                lines.append(f"  - {store['name']}: {v['units']} units [item {item_id}] | {fmt_money(v['value'], 'USD')}")
        pages.append("\n".join(lines))

    if page == 1:
        # Payments received
        lines = []
        lines.append("─────────────────────────────\n💰 PAYMENTS RECEIVED")
        for name, v in data["payments_by_person"].items():
            if name:
                lines.append(f"  {name}: {fmt_money(v['local'], v['currency'])} | {fmt_money(v['usd'], 'USD')}")
        lines.append(f"  Total USD Received: {fmt_money(data['total_usd_received'], 'USD')}")
        pages.append("\n".join(lines))
    if page == 2:
        # Payouts
        lines = []
        lines.append("─────────────────────────────\n💸 PAYOUTS TO PARTNERS")
        for name, v in data["payouts_by_partner"].items():
            if name:
                lines.append(f"  {name}: {fmt_money(v['local'], v['currency'])} | {fmt_money(v['usd'], 'USD')}")
        lines.append(f"  Total USD Paid Out: {fmt_money(data['total_usd_paid'], 'USD')}")
        pages.append("\n".join(lines))
    if page == 3:
        # Inventory
        lines = []
        lines.append("─────────────────────────────\n📦 INVENTORY")
        for item_id, v in data["inventory_by_item"].items():
            lines.append(f"  {item_id}: {v['units']} units = {fmt_money(v['market'], 'USD')}")
        lines.append(f"  Total Inventory Value: {fmt_money(sum(v['market'] for v in data['inventory_by_item'].values()), 'USD')}")
        # Unreconciled inventory
        if data["unreconciled"]:
            lines.append("\n⚠️ UNRECONCILED INVENTORY")
            for item_id, v in data["unreconciled"].items():
                lines.append(f"  - {item_id}: {v['units']} units ({fmt_money(v['market'], 'USD')})")
        pages.append("\n".join(lines))
    if page == 4:
        # Expenses
        lines = []
        lines.append("─────────────────────────────\n📉 EXPENSES")
        for e in data["expenses"]:
            lines.append(f"  {fmt_date(e['date'])}: {fmt_money(abs(e['amount']), e['currency'])}")
        lines.append(f"  Total Expenses: {fmt_money(data['total_expenses'], 'USD')}")
        pages.append("\n".join(lines))
    if page == 5:
        # Financial position
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
    # Return to current page view
    return await owner_show_report(update, context)

# --- Register Handlers ---
def register_owner_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_owner_report_menu, pattern="^rep_owner$"))
    app.add_handler(CallbackQueryHandler(owner_choose_scope, pattern="^owner_range_"))
    app.add_handler(CallbackQueryHandler(owner_paginate, pattern="^owner_page_"))
    app.add_handler(CallbackQueryHandler(owner_export_pdf, pattern="^owner_export_pdf$"))
    app.add_handler(CallbackQueryHandler(lambda u, c: None, pattern="^main_menu$"))  # back to menu

    app.add_handler(MessageHandler(None, owner_save_custom_start))  # for date input

