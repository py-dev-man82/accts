# handlers/reports/store_report.py

import logging
from datetime import datetime, timedelta
from typing import List, Dict
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ConversationHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_ledger
from secure_db import secure_db

(
    STORE_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_PAGE,
) = range(5)

_PAGE_SIZE = 8

def _reset_state(ctx):
    for k in ("store_id", "start_date", "end_date", "page", "scope"):
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
            f"{s['name']} ({s['currency']})", callback_data=f"sreport_{s.doc_id}"
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

    # Defensive: Make sure store_id is set and store exists
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

    # --- SALES (only direct store sales + handling fees as credits) ---
    sledger = get_ledger("store", sid)
    direct_sales = [
        e for e in sledger if e.get("entry_type") == "sale" and _between(e.get("date", ""), start, end)
    ]
    handling_credits = [
        e for e in sledger if e.get("entry_type") == "handling_fee" and _between(e.get("date", ""), start, end)
    ]
    all_sales = direct_sales + handling_credits

    # Format sales lines
    sales_lines = []
    for s in sorted(all_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True):
        if s.get("entry_type") == "sale":
            qty = s.get('quantity', 0)
            price = s.get('unit_price', s.get('unit_cost', 0))
            sales_lines.append(
                f"• {fmt_date(s['date'])}: [{s.get('item_id','?')}] {qty} × {fmt_money(price, cur)} = {fmt_money(abs(qty * price), cur)}"
            )
        elif s.get("entry_type") == "handling_fee":
            # Handling fee as Owner Sale (income)
            amt = s.get('amount', 0)
            item = s.get('item_id', '')
            qty = s.get('quantity', '')
            sales_lines.append(
                f"• {fmt_date(s['date'])}: [Owner Sale] {fmt_money(amt, cur)}"
            )

    # Units Sold (by item) - only direct sales
    unit_summary = []
    item_totals = defaultdict(lambda: {"units": 0, "value": 0.0})
    for s in direct_sales:
        iid = s.get('item_id', '?')
        qty = abs(s.get('quantity', 0))
        val = abs(s.get('quantity', 0) * s.get('unit_price', s.get('unit_cost', 0)))
        item_totals[iid]["units"] += qty
        item_totals[iid]["value"] += val
    for iid, sums in item_totals.items():
        unit_summary.append(f"- [{iid}] : {sums['units']} units, {fmt_money(sums['value'], cur)}")

    # Total Sales: sum direct sales and handling fee credits
    total_sales = sum(abs(s.get('quantity', 0) * s.get('unit_price', s.get('unit_cost', 0))) for s in direct_sales) \
        + sum(s.get('amount', 0) for s in handling_credits)

    # --- PAYMENTS (payments *received* by store) ---
    payments = [
        e for e in sledger if e.get("entry_type") in ("payment", "payment_recv") and _between(e.get("date", ""), start, end)
    ]
    payment_lines = []
    for p in sorted(payments, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True):
        amount = p.get('amount', 0)
        fee_perc = p.get('fee_perc', 0)
        fx_rate = p.get('fx_rate', 0)
        inv_fx = 1 / fx_rate if fx_rate else 0
        usd_amt = p.get('usd_amt', 0)
        payment_lines.append(
            f"• {fmt_date(p.get('date', ''))}: {fmt_money(amount, cur)}  |  {fee_perc:g}%  |  {inv_fx:.4f}  |  {fmt_money(usd_amt, 'USD')}"
        )
    total_pay_local = sum(p.get('amount', 0) for p in payments)
    total_pay_usd = sum(p.get('usd_amt', 0) for p in payments)

    # --- EXPENSES (NO handling fees here) ---
    expenses = [e for e in sledger if e.get("entry_type") == "expense" and _between(e.get("date", ""), start, end)]
    stockins = [e for e in sledger if e.get("entry_type") == "stockin" and _between(e.get("date", ""), start, end)]

    # Inventory purchase (stock-in) lines
    inventory_purchase_lines = []
    total_inventory_purchase = 0
    for s in sorted(stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True):
        qty = s.get('quantity', 0)
        price = s.get('unit_price', 0)
        total = qty * price
        total_inventory_purchase += total
        inventory_purchase_lines.append(f"   - {fmt_date(s.get('date', ''))}: [{s.get('item_id')}] {qty} @ {fmt_money(price, cur)} = {fmt_money(total, cur)}")

    # Expense lines
    expense_lines = []
    other_total = sum(abs(e.get("amount", 0)) for e in expenses)
    if expenses:
        expense_lines.append("• 🧾 Other Expenses")
        for e in expenses:
            expense_lines.append(f"   - {fmt_date(e.get('date', ''))}: {fmt_money(abs(e.get('amount', 0)), cur)}")
        expense_lines.append(f"📊 Total Other Expenses: {fmt_money(other_total, cur)}")
    if inventory_purchase_lines:
        expense_lines.append("📦 Inventory Purchase:")
        expense_lines += inventory_purchase_lines
        expense_lines.append(f"📊 Total Inventory Purchase: {fmt_money(total_inventory_purchase, cur)}")
    total_all_expenses = other_total + total_inventory_purchase
    if expense_lines:
        expense_lines.append(f"\n📊 Total All Expenses: {fmt_money(total_all_expenses, cur)}")

    # --- CURRENT STOCK (all time, not just in period) ---
    all_stockins = [e for e in sledger if e.get("entry_type") == "stockin"]
    all_sales = [e for e in sledger if e.get("entry_type") == "sale"]
    stock_balance = defaultdict(int)
    for s in all_stockins:
        stock_balance[s.get("item_id")] += s.get("quantity", 0)
    for s in all_sales:
        stock_balance[s.get("item_id")] -= abs(s.get("quantity", 0))

    market_prices = {}
    for item in stock_balance:
        price = get_last_sale_price(all_sales, item)
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

    # --- FINANCIAL POSITION ---
    balance = total_sales - total_pay_local - total_all_expenses

    # --- Output lines by scope ---
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

# Register
def register_store_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_store_report_menu, pattern="^rep_store$"))
    app.add_handler(CallbackQueryHandler(select_date_range, pattern="^sreport_"))
    app.add_handler(CallbackQueryHandler(choose_scope, pattern="^range_"))
    app.add_handler(CallbackQueryHandler(show_report, pattern="^scope_"))
    app.add_handler(CallbackQueryHandler(paginate, pattern="^page_"))
    # Add custom date input if using MessageHandler in your main bot.py

