# handlers/reports/partner_report.py

import logging
from datetime import datetime, timedelta
from typing import List, Dict
from collections import defaultdict
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ConversationHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_ledger
from secure_db import secure_db

(
    PARTNER_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_PAGE,
) = range(5)

_PAGE_SIZE = 8

def _reset_state(ctx):
    for k in ("partner_id", "start_date", "end_date", "page", "scope"):
        ctx.user_data.pop(k, None)

async def _goto_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_state(context)
    from bot import start
    return await start(update, context)

def _paginate(lst: List[dict], page: int) -> List[dict]:
    start = page * _PAGE_SIZE
    return lst[start : start + _PAGE_SIZE]

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

@require_unlock
async def show_partner_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_state(context)
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "⚠️ No partners found.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
            ),
        )
        return ConversationHandler.END

    btns = [
        InlineKeyboardButton(
            f"{p['name']} ({p['currency']})", callback_data=f"preport_{p.doc_id}"
        )
        for p in partners
    ]
    rows = [btns[i : i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📄 Select partner:",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return PARTNER_SELECT

async def select_date_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["partner_id"] = pid

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 Last 7 days", callback_data="range_week")],
            [InlineKeyboardButton("📆 Custom Range", callback_data="range_custom")],
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
        if choice == "range_week":
            context.user_data["start_date"] = datetime.now() - timedelta(days=7)
            context.user_data["end_date"] = datetime.now()
        elif choice == "range_custom":
            return await ask_custom_start(update, context)

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📝 Full Report", callback_data="scope_full"),
                InlineKeyboardButton("🛒 Sales Only", callback_data="scope_sales"),
            ],
            [
                InlineKeyboardButton("💵 Payments Only", callback_data="scope_payments")
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
    ctx["scope"] = update.callback_query.data.split("_")[-1]

    pid = ctx["partner_id"]
    partner = secure_db.table("partners").get(doc_id=pid)
    cur = partner["currency"]
    start, end = ctx["start_date"], ctx["end_date"]

    # SALES
    sales = []
    for c in secure_db.all("customers"):
        if c["name"] == partner["name"]:
            sales += [
                e for e in get_ledger("customer", c.doc_id)
                if e.get("entry_type") == "sale" and _between(e.get("date", ""), start, end)
            ]
    sales += [
        e for e in get_ledger("partner", pid)
        if e.get("entry_type") == "sale" and _between(e.get("date", ""), start, end)
    ]
    sale_items = defaultdict(list)
    for s in sales:
        sale_items[s.get("item_id", "?")].append(s)

    # PAYMENTS (combine payouts and partner-as-customer payments)
    payouts = [
        e for e in get_ledger("partner", pid)
        if e.get("entry_type") == "payment" and _between(e.get("date", ""), start, end)
    ]
    customer_payments = []
    for c in secure_db.all("customers"):
        if c["name"] == partner["name"]:
            customer_payments += [
                e for e in get_ledger("customer", c.doc_id)
                if e.get("entry_type") == "payment" and _between(e.get("date", ""), start, end)
            ]
    payments = payouts + customer_payments

    # --- PAYMENTS: show fee percent and FX rate ---
    payment_lines = []
    for p in sorted(payments, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True):
        amount = p.get('amount', 0)
        fee_perc = p.get('fee_perc', 0)
        fx_rate = p.get('fx_rate', 0)
        usd_amt = p.get('usd_amt', 0)
        payment_lines.append(
            f"• {fmt_date(p.get('date', ''))}: {fmt_money(amount, cur)}  |  {fee_perc:g}%  |  {fx_rate:.4f}  |  {fmt_money(usd_amt, 'USD')}"
        )
    total_pay_local = sum(p.get('amount', 0) for p in payments)
    total_pay_usd = sum(p.get('usd_amt', 0) for p in payments)

    # EXPENSES
    pledger = get_ledger("partner", pid)
    handling_fees = [e for e in pledger if e.get("entry_type") == "handling_fee" and _between(e.get("date", ""), start, end)]
    other_expenses = [e for e in pledger if e.get("entry_type") == "expense" and _between(e.get("date", ""), start, end)]

    # STOCK-INS
    stockins = [
        e for e in pledger if e.get("entry_type") == "stockin" and _between(e.get("date", ""), start, end)
    ]

    # CURRENT STOCK @ MARKET
    stock_balance = defaultdict(int)
    for s in stockins:
        stock_balance[s.get("item_id")] += s.get("quantity", 0)
    for item, sales_list in sale_items.items():
        for s in sales_list:
            stock_balance[item] -= abs(s.get("quantity", 0))
    market_prices = {}
    for item in stock_balance:
        price = get_last_sale_price(sales, item)
        if price == 0:
            stk = [e for e in stockins if e.get("item_id") == item]
            if stk:
                price = sorted(stk, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0].get("unit_price", stk[-1].get("unit_cost", 0))
        market_prices[item] = price or 0

    sales_lines = []
    for item_id, entries in sale_items.items():
        for s in sorted(entries, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True):
            qty = s.get('quantity', 0)
            price = s.get('unit_price', s.get('unit_cost', 0))
            sales_lines.append(
                f"• {fmt_date(s.get('date', ''))}: [{item_id}] {qty} × {fmt_money(price, cur)} = {fmt_money(abs(qty * price), cur)}"
            )
    unit_summary = []
    for item_id, entries in sale_items.items():
        units = sum(abs(s.get('quantity', 0)) for s in entries)
        value = sum(abs(s.get('quantity', 0) * s.get('unit_price', s.get('unit_cost', 0))) for s in entries)
        unit_summary.append(f"- [{item_id}] : {units} units, {fmt_money(value, cur)}")
    total_sales = sum(abs(s.get('quantity', 0) * s.get('unit_price', s.get('unit_cost', 0))) for s in sales)

    expense_lines = []
    if handling_fees:
        expense_lines.append("• 💳 Handling Fees")
        for h in handling_fees:
            expense_lines.append(f"   - {fmt_date(h.get('date', ''))}: {fmt_money(abs(h.get('amount', 0)), cur)}")
        expense_lines.append(f"📊 Total Handling Fees: {fmt_money(sum(abs(h.get('amount', 0)) for h in handling_fees), cur)}")
    if other_expenses:
        expense_lines.append("• 🧾 Other Expenses")
        for e in other_expenses:
            expense_lines.append(f"   - {fmt_date(e.get('date', ''))}: {fmt_money(abs(e.get('amount', 0)), cur)}")
        expense_lines.append(f"📊 Total Other Expenses: {fmt_money(sum(abs(e.get('amount', 0)) for e in other_expenses), cur)}")

    stockin_lines = []
    for s in sorted(stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True):
        qty = s.get('quantity', 0)
        price = s.get('unit_price', s.get('unit_cost', 0))
        total = qty * price
        stockin_lines.append(f"   - {fmt_date(s.get('date', ''))}: [{s.get('item_id')}] {qty} @ {fmt_money(price, cur)} = {fmt_money(total, cur)}")

    current_stock_lines = []
    stock_value = 0
    for item, qty in stock_balance.items():
        if qty > 0:
            mp = market_prices[item]
            val = qty * mp
            current_stock_lines.append(f"   - [{item}] {qty} × {fmt_money(mp, cur)} = {fmt_money(val, cur)}")
            stock_value += val

    total_handling = sum(abs(h.get("amount", 0)) for h in handling_fees)
    total_other_exp = sum(abs(e.get("amount", 0)) for e in other_expenses)
    balance = total_sales - total_pay_local - total_handling - total_other_exp

    lines = []
    if ctx["scope"] in ("full", "sales"):
        lines.append("🛒 Sales")
        lines += sales_lines
        lines.append("")
        lines.append("📦 Units Sold (by item):")
        lines += unit_summary
        lines.append(f"\n📊 Total Sales: {fmt_money(total_sales, cur)}\n")
    if ctx["scope"] in ("full", "payments"):
        lines.append("💵 Payments")
        lines += payment_lines
        lines.append(f"\n📊 Total Payments: {fmt_money(total_pay_local, cur)} → {fmt_money(total_pay_usd, 'USD')}\n")
    if ctx["scope"] == "full":
        lines.append("🧾 Expenses")
        lines += expense_lines
        lines.append("")
        lines.append("📦 Inventory")
        if stockin_lines:
            lines.append("• Stock-Ins:")
            lines += stockin_lines
        if current_stock_lines:
            lines.append("• Current Stock @ market:")
            lines += current_stock_lines
        lines.append(f"\n📊 Stock Value: {fmt_money(stock_value, cur)}\n")
        lines.append("📊 Financial Position")
        lines.append(f"Balance (S − P − E): {fmt_money(balance, cur)}")
        lines.append(f"Inventory Value:     {fmt_money(stock_value, cur)}")
        lines.append("────────────────────────────────────")
        lines.append(f"Total Position:      {fmt_money(balance + stock_value, cur)}")

    nav = []
    if ctx["page"] > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="page_prev"))
    nav.append(InlineKeyboardButton("📄 Export PDF", callback_data="export_pdf"))
    nav.append(InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))

    await update.callback_query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([nav]),
        parse_mode="Markdown"
    )
    return REPORT_PAGE

@require_unlock
async def paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == "page_next":
        context.user_data["page"] += 1
    elif update.callback_query.data == "page_prev":
        context.user_data["page"] = max(0, context.user_data["page"] - 1)
    return await show_report(update, context)

@require_unlock
async def export_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (Add your actual PDF generation code here.)
    await update.callback_query.answer("Generating PDF …")
    # ... PDF logic ...
    await update.effective_message.reply_document(
        document=b'somefile.pdf',  # Replace with your BytesIO object/filename
        filename="Partner_Report.pdf",
        caption="Partner PDF report"
    )
    return REPORT_PAGE


def register_partner_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_partner_report_menu, pattern="^rep_part$"))
    app.add_handler(CallbackQueryHandler(select_date_range, pattern="^preport_\\d+$"))
    app.add_handler(CallbackQueryHandler(choose_scope, pattern="^range_(week|custom)$"))
    app.add_handler(CallbackQueryHandler(show_report, pattern="^scope_(full|sales|payments)$"))
    app.add_handler(CallbackQueryHandler(paginate, pattern="^page_(next|prev)$"))
    # If you have export_pdf and _goto_main_menu handlers:
    app.add_handler(CallbackQueryHandler(export_pdf, pattern="^export_pdf$"))
    app.add_handler(CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"))
