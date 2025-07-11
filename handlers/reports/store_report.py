# handlers/reports/store_report.py

import logging
from datetime import datetime, timedelta
from typing import List, Dict
from collections import defaultdict
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import CallbackQueryHandler, ConversationHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_ledger
from secure_db import secure_db

# === Import shared report utilities ===
from handlers.reports.report_utils import (
    compute_store_inventory,
    compute_store_sales,
    compute_payouts,
)

(
    STORE_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_PAGE,
) = range(5)

def _reset_state(ctx):
    for k in ("store_id", "start_date", "end_date", "page", "scope"):
        ctx.user_data.pop(k, None)

async def _goto_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_state(context)
    from bot import start
    return await start(update, context)

def _between(date_str: str, start: datetime, end: datetime) -> bool:
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

# === Diagnostics function using shared logic ===
def store_report_diagnostic(sid, secure_db, get_ledger):
    print(f"\n==== STORE REPORT DIAGNOSTIC (Store {sid}) ====")
    store_inventory = compute_store_inventory(secure_db, get_ledger)
    store_sales = compute_store_sales(secure_db, get_ledger)
    payouts = compute_payouts(secure_db, get_ledger)
    print(f"Store Inventory: {store_inventory.get(sid, {})}")
    print(f"Store Sales: {store_sales.get(sid, {})}")
    print(f"Payouts: {[p for p in payouts if p.get('store_id') == sid]}")
    print("==== END STORE REPORT DIAGNOSTIC ====\n")

def build_store_report_lines(ctx, start, end, sid, cur, secure_db, get_ledger):
    store = secure_db.table("stores").get(doc_id=sid)
    store_name = store["name"]
    store_customer_ids = [cust.doc_id for cust in secure_db.all("customers") if cust["name"] == store_name]

    # SALES
    store_sales = []
    for cust in secure_db.all("customers"):
        # Try all possible customer account types present in your ledgers
        for acct_type in ["general", "store", "partner", "store_customer"]:
            ledger = get_ledger(acct_type, cust.doc_id)
            for e in ledger:
                if (
                    e.get("entry_type") == "sale"
                    and e.get("store_id") == sid
                    and _between(e.get("date", ""), start, end)
               ):
                    store_sales.append(e)
    sales_sorted = sorted(store_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)

    # HANDLING FEES (from store ledger only)
    sledger = get_ledger("store", sid)
    handling_fees = [e for e in sledger if e.get("entry_type") == "handling_fee" and _between(e.get("date", ""), start, end)]
    fees_sorted = sorted(handling_fees, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)

    # PAYMENTS
    store_payments = []
    for cust_id in store_customer_ids:
        for acct_type in ["customer", "store"]:
            cust_ledger = get_ledger(acct_type, cust_id)
            for p in cust_ledger:
                if p.get("entry_type") == "payment" and _between(p.get("date", ""), start, end):
                    store_payments.append(p)
    payment_lines = []
    for p in sorted(store_payments, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True):
        amount = p.get('amount', 0)
        fee_perc = p.get('fee_perc', 0)
        fx_rate = p.get('fx_rate', 0)
        usd_amt = p.get('usd_amt', 0)
        payment_lines.append(
            f"• {fmt_date(p.get('date', ''))}: {fmt_money(amount, cur)}  |  Fee: {fee_perc:g}%  |  FX: {fx_rate:.4f}  |  USD: {fmt_money(usd_amt, 'USD')}"
        )
    total_pay_local = sum(p.get('amount', 0) for p in store_payments)
    total_pay_usd = sum(p.get('usd_amt', 0) for p in store_payments)

    # INVENTORY: all-time for current, in-period for ins
    all_stockins = []
    for e in get_ledger("store", sid):
        if e.get("entry_type") == "stockin":
            all_stockins.append(e)
    for partner in secure_db.all("partners"):
        pledger = get_ledger("partner", partner.doc_id)
        for e in pledger:
            if e.get("entry_type") == "stockin" and e.get("store_id") == sid:
                all_stockins.append(e)

    stockin_lines = []
    for e in sorted(all_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True):
        if _between(e.get("date", ""), start, end):
            item = e.get("item_id", "?")
            qty = e.get("quantity", 0)
            stockin_lines.append(f"- {fmt_date(e['date'])} [{item}] × {qty}")

    # ALL-TIME CALCS for financials and inventory
    alltime_sales = []
    for cust_id in store_customer_ids:
        for acct_type in ["customer", "store_customer"]:
            cust_ledger = get_ledger(acct_type, cust_id)
            for e in cust_ledger:
                if e.get("entry_type") == "sale":
                    alltime_sales.append(e)
    alltime_fees = [e for e in get_ledger("store", sid) if e.get("entry_type") == "handling_fee"]
    alltime_payments = []
    for cust_id in store_customer_ids:
        for acct_type in ["general", "store", "partner"]:
            cust_ledger = get_ledger(acct_type, cust_id)
            for p in cust_ledger:
                if p.get("entry_type") == "payment":
                    alltime_payments.append(p)
    alltime_expenses = [e for e in get_ledger("store", sid) if e.get("entry_type") == "expense"]

    sales_lines = []
    for s in sales_sorted:
        qty = s.get('quantity', 0)
        price = s.get('unit_price', s.get('unit_cost', 0))
        sales_lines.append(
            f"• {fmt_date(s['date'])}: [{s.get('item_id','?')}] {qty} × {fmt_money(price, cur)} = {fmt_money(abs(qty * price), cur)}"
        )
    fee_lines = []
    for f in fees_sorted:
        qty = abs(f.get('quantity', 0)) or 1
        amt = f.get('amount', 0)
        unit_fee = amt / qty if qty else amt
        item = f.get('item_id', '?')
        fee_lines.append(
            f"• {fmt_date(f['date'])}: [{item}] {qty} × {fmt_money(unit_fee, cur)} = {fmt_money(amt, cur)}"
        )
    unit_summary = []
    item_totals = defaultdict(lambda: {"units": 0, "value": 0.0})
    for s in sales_sorted:
        iid = s.get('item_id', '?')
        qty = abs(s.get('quantity', 0))
        val = abs(s.get('quantity', 0) * s.get('unit_price', s.get('unit_cost', 0)))
        item_totals[iid]["units"] += qty
        item_totals[iid]["value"] += val
    for iid, sums in item_totals.items():
        unit_summary.append(f"- [{iid}] : {sums['units']} units, {fmt_money(sums['value'], cur)}")

    total_sales_only = sum(abs(s.get('quantity', 0) * s.get('unit_price', s.get('unit_cost', 0))) for s in sales_sorted)
    total_fees_only = sum(abs(f.get('amount', 0)) for f in fees_sorted)
    grand_total = total_sales_only + total_fees_only

    sledger = get_ledger("store", sid)
    expenses = [e for e in sledger if e.get("entry_type") == "expense" and _between(e.get("date", ""), start, end)]
    expense_lines = []
    other_total = sum(abs(e.get("amount", 0)) for e in expenses)
    if expenses:
        expense_lines.append("• 🧾 Other Expenses")
        for e in expenses:
            expense_lines.append(f"   - {fmt_date(e.get('date', ''))}: {fmt_money(abs(e.get('amount', 0)), cur)}")
        expense_lines.append(f"📊 Total Other Expenses: {fmt_money(other_total, cur)}")

    # Current inventory at market
    store_inventory = compute_store_inventory(secure_db, get_ledger)
    stock_balance = store_inventory.get(sid, defaultdict(int))
    market_prices = {}
    for item in stock_balance:
        price = get_last_sale_price(alltime_sales, item)
        if price == 0:
            stk = [e for e in all_stockins if e.get("item_id") == item]
            if stk:
                price = sorted(stk, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0].get("unit_price", 0)
        market_prices[item] = price or 0

    current_stock_lines = []
    stock_value = 0
    for item, qty in stock_balance.items():
        if qty > 0:
            mp = market_prices[item]
            val = qty * mp
            current_stock_lines.append(f"   - [{item}] {qty} × {fmt_money(mp, cur)} = {fmt_money(val, cur)}")
            stock_value += val

    # Financial position (all time)
    total_sales = sum(abs(s.get('quantity', 0) * s.get('unit_price', s.get('unit_cost', 0))) for s in alltime_sales)
    total_fees = sum(abs(f.get('amount', 0)) for f in alltime_fees)
    total_pay = sum(p.get('amount', 0) for p in alltime_payments)
    total_exp = sum(abs(e.get("amount", 0)) for e in alltime_expenses)
    balance = total_sales + total_fees - total_pay - total_exp

    # ---- SECTIONED LINES FOR MATCHED OUTPUT ----
    lines = []
    lines.append(f"📄 Account: {store_name}")
    lines.append(f"🗓️ Period: {start.strftime('%d/%m/%Y')} → {end.strftime('%d/%m/%Y')}")
    lines.append("──────────────────────────────\n")

    # Sales Section
    lines.append("🛒 Sales")
    lines += sales_lines if sales_lines else ["(none)"]
    lines.append("")
    lines.append("💳 Handling Fees")
    lines += fee_lines if fee_lines else ["(none)"]
    lines.append("")
    lines.append("📦 Units Sold (by item):")
    lines += unit_summary if unit_summary else ["(none)"]
    lines.append(f"\n📊 Total Sales: {fmt_money(total_sales_only, cur)}")
    lines.append(f"📊 Total Handling Fees: {fmt_money(total_fees_only, cur)}\n")
    lines.append(f"📊 Grand Total (Sales + Fees): {fmt_money(grand_total, cur)}")
    lines.append("──────────────────────────────\n")

    # Payments Section
    lines.append("💵 Payments")
    lines += payment_lines if payment_lines else ["(none)"]
    lines.append(f"\n📊 Total Payments: {fmt_money(total_pay_local, cur)} → {fmt_money(total_pay_usd, 'USD')}")
    lines.append("──────────────────────────────\n")

    # Expenses Section
    lines.append("🧾 Expenses")
    lines += expense_lines if expense_lines else ["(none)"]
    total_all_expenses = other_total  # (Sum up all types of expenses as desired)
    lines.append(f"\n📊 Total All Expenses: {fmt_money(total_all_expenses, cur)}")
    lines.append("──────────────────────────────\n")

    # Inventory Section
    lines.append("📦 Inventory")
    if stockin_lines:
        lines.append("• In :  ")
        lines += stockin_lines
    if current_stock_lines:
        lines.append("\n• Current Stock On Hand @ market: ")
        lines += current_stock_lines
    lines.append(f"\n📊 Stock Value: {fmt_money(stock_value, cur)}")
    lines.append("──────────────────────────────\n")

    # Financial Position Section
    lines.append("📊 Financial Position (ALL TIME)")
    lines.append(f"Balance (S + Fees − P − E): {fmt_money(balance, cur)}")
    lines.append(f"Inventory Value:     {fmt_money(stock_value, cur)}")
    lines.append("────────────────────────────────────")
    lines.append(f"Total Position:      {fmt_money(balance + stock_value, cur)}")

    return lines

@require_unlock
async def show_store_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_state(context)
    stores = secure_db.all("stores")
    if not stores:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "⚠️ No stores found.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
            ),
        )
        return ConversationHandler.END

    btns = [
        InlineKeyboardButton(
            f"{s['name']} ({s['currency']})", callback_data=f"store_sreport_{s.doc_id}"
        )
        for s in stores
    ]
    rows = [btns[i : i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📄 Select store:",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return STORE_SELECT

async def select_date_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split("_")[-1])
    context.user_data["store_id"] = sid

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 Last 7 days", callback_data="store_range_week")],
            [InlineKeyboardButton("📆 Custom Range", callback_data="store_range_custom")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        ]
    )
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return DATE_RANGE_SELECT

async def ask_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Enter start date DDMMYYYY:",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
        ),
    )
    return CUSTOM_DATE_INPUT

async def save_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    try:
        sd = datetime.strptime(txt, "%d%m%Y")
    except ValueError:
        await update.message.reply_text("❌ Format DDMMYYYY please.")
        return CUSTOM_DATE_INPUT

    context.user_data["start_date"] = sd
    context.user_data["end_date"] = datetime.now()
    return await choose_scope(update, context)

async def choose_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if getattr(update, "callback_query", None):
        await update.callback_query.answer()
        choice = update.callback_query.data
        if choice == "store_range_week":
            context.user_data["start_date"] = datetime.now() - timedelta(days=7)
            context.user_data["end_date"] = datetime.now()
        elif choice == "store_range_custom":
            return await ask_custom_start(update, context)

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📝 Full Report", callback_data="store_scope_full"),
                InlineKeyboardButton("🛒 Sales Only", callback_data="store_scope_sales"),
            ],
            [
                InlineKeyboardButton("💵 Payments Only", callback_data="store_scope_payments")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        ]
    )
    if getattr(update, "callback_query", None):
        await update.callback_query.edit_message_text(
            "Choose report scope:", reply_markup=kb
        )
    else:
        await update.message.reply_text("Choose report scope:", reply_markup=kb)
    return REPORT_SCOPE_SELECT

@require_unlock
async def show_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx = context.user_data
    ctx.setdefault("page", 0)
    ctx["scope"] = update.callback_query.data.replace("store_scope_", "")

    if "store_id" not in ctx:
        await update.callback_query.edit_message_text("⚠️ Please select a store first from the report menu.")
        return ConversationHandler.END

    sid = ctx["store_id"]
    store = secure_db.table("stores").get(doc_id=sid)
    if not store:
        await update.callback_query.edit_message_text("⚠️ Store not found.")
        return ConversationHandler.END

    cur = store["currency"]
    start, end = ctx["start_date"], ctx["end_date"]

    # Print diagnostics (NEW)
    store_report_diagnostic(sid, secure_db, get_ledger)

    lines = build_store_report_lines(ctx, start, end, sid, cur, secure_db, get_ledger)

    nav = []
    nav.append(InlineKeyboardButton("📄 Export PDF", callback_data="store_export_pdf"))
    nav.append(InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))

    await update.callback_query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([nav]),
        parse_mode="Markdown"
    )
    return REPORT_PAGE

@require_unlock
async def export_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Generating PDF …")
    ctx = context.user_data

    sid = ctx["store_id"]
    store = secure_db.table("stores").get(doc_id=sid)
    cur = store["currency"]
    store_name = store["name"]

    start, end = ctx["start_date"], ctx["end_date"]
    lines = build_store_report_lines(ctx, start, end, sid, cur, secure_db, get_ledger)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, 760, f"Report ({store_name})")
    pdf.setFont("Helvetica", 10)

    y = 740
    def pdf_add(text, font="Helvetica", size=10, gap=15):
        nonlocal y
        if y < 60:
            pdf.showPage()
            pdf.setFont(font, size)
            y = 760
        pdf.setFont(font, size)
        pdf.drawString(40, y, text)
        y -= gap

    for line in lines:
        for subline in line.split("\n"):
            pdf_add(subline)
    pdf.save()
    buffer.seek(0)
    pdf_input = InputFile(buffer, filename=f"Report ({store_name}).pdf")
    await update.effective_message.reply_document(pdf_input)
    await update.callback_query.answer("PDF exported.", show_alert=False)
    return REPORT_PAGE

def register_store_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_store_report_menu, pattern="^rep_store$"))
    app.add_handler(CallbackQueryHandler(select_date_range, pattern="^store_sreport_"))
    app.add_handler(CallbackQueryHandler(choose_scope, pattern="^store_range_"))
    app.add_handler(CallbackQueryHandler(show_report, pattern="^store_scope_"))
    app.add_handler(CallbackQueryHandler(export_pdf, pattern="^store_export_pdf"))
