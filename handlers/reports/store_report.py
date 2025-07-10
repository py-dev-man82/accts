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

def store_sales_diagnostic(store_id, secure_db, get_ledger, start=None, end=None):
    print("\n==== STORE REPORT DIAGNOSTIC ====")
    # SALES
    found_sales = False
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            cust_ledger = get_ledger(acct_type, cust.doc_id)
            for e in cust_ledger:
                if e.get("entry_type") == "sale" and e.get("store_id") == store_id and (not start or _between(e.get("date", ""), start, end)):
                    if not found_sales:
                        print("SALES found in customer/store_customer ledgers for this store_id:")
                        found_sales = True
                    print(f"  [{acct_type}] Customer: {cust['name']} Ledger:", e)
    if not found_sales:
        print("!! No sales found in any customer or store_customer ledger for this store_id.")

    # HANDLING FEES
    sledger = get_ledger("store", store_id)
    found_fees = False
    for e in sledger:
        if e.get("entry_type") == "handling_fee" and (not start or _between(e.get("date", ""), start, end)):
            if not found_fees:
                print("HANDLING FEES in this store's own ledger (credits):")
                found_fees = True
            print("  Ledger:", e)
    if not found_fees:
        print("!! No handling fee entries found in this store's own ledger.")

    # PAYMENTS
    found_payments = False
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            cust_ledger = get_ledger(acct_type, cust.doc_id)
            for p in cust_ledger:
                if p.get("entry_type") == "payment" and p.get("store_id") == store_id and (not start or _between(p.get("date", ""), start, end)):
                    if not found_payments:
                        print("PAYMENTS found in customer/store_customer ledgers for this store_id:")
                        found_payments = True
                    print(f"  [{acct_type}] Customer: {cust['name']} Ledger:", p)
    if not found_payments:
        print("!! No payments found in any customer or store_customer ledger for this store_id.")

    # INVENTORY (stock-in)
    found_inventory = False
    for e in sledger:
        if e.get("entry_type") == "stockin" and (not start or _between(e.get("date", ""), start, end)):
            if not found_inventory:
                print("INVENTORY (stock-in) entries in this store's own ledger:")
                found_inventory = True
            print("  Ledger:", e)
    for partner in secure_db.all("partners"):
        pledger = get_ledger("partner", partner.doc_id)
        for e in pledger:
            if e.get("entry_type") == "stockin" and e.get("store_id") == store_id and (not start or _between(e.get("date", ""), start, end)):
                if not found_inventory:
                    print("INVENTORY (stock-in) entries in partner ledgers for this store_id:")
                    found_inventory = True
                print(f"  [partner] Partner: {partner['name']} Ledger:", e)
    if not found_inventory:
        print("!! No stock-in entries found in store or partner ledgers for this store_id.")

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

    # --- DIAGNOSTIC: Print all sales, fees, payments, inventory for this store ---
    store_sales_diagnostic(sid, secure_db, get_ledger, start, end)

    # SALES: all customer/store_customer sales handled by this store (by store_id on the sale entry)
    store_sales = []
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            cust_ledger = get_ledger(acct_type, cust.doc_id)
            for e in cust_ledger:
                if e.get("entry_type") == "sale" and e.get("store_id") == sid and _between(e.get("date", ""), start, end):
                    store_sales.append(e)

    # HANDLING FEES: from store ledger ONLY (these are credits to the store)
    sledger = get_ledger("store", sid)
    handling_fees = [e for e in sledger if e.get("entry_type") == "handling_fee" and _between(e.get("date", ""), start, end)]

    # PAYMENTS: all customer/store_customer payments for this store
    store_payments = []
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            cust_ledger = get_ledger(acct_type, cust.doc_id)
            for p in cust_ledger:
                if p.get("entry_type") == "payment" and p.get("store_id") == sid and _between(p.get("date", ""), start, end):
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

    # --- INVENTORY DATA: ---
    # (1) all_stockins for inventory balance (ALL TIME, from store and partner ledgers)
    all_stockins = []
    for e in get_ledger("store", sid):
        if e.get("entry_type") == "stockin":
            all_stockins.append(e)
    for partner in secure_db.all("partners"):
        pledger = get_ledger("partner", partner.doc_id)
        for e in pledger:
            if e.get("entry_type") == "stockin" and e.get("store_id") == sid:
                all_stockins.append(e)

    # (2) Filter stock-in lines for display (by date)
    stockin_lines = []
    for e in sorted(all_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True):
        if _between(e.get("date", ""), start, end):
            item = e.get("item_id", "?")
            qty = e.get("quantity", 0)
            stockin_lines.append(f"- {fmt_date(e['date'])} [{item}] × {qty}")

    # --- ALL-TIME DATA for financial position ---
    # All-time sales
    alltime_sales = []
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            cust_ledger = get_ledger(acct_type, cust.doc_id)
            for e in cust_ledger:
                if e.get("entry_type") == "sale" and e.get("store_id") == sid:
                    alltime_sales.append(e)
    # All-time handling fees
    alltime_fees = [e for e in get_ledger("store", sid) if e.get("entry_type") == "handling_fee"]
    # All-time payments
    alltime_payments = []
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            cust_ledger = get_ledger(acct_type, cust.doc_id)
            for p in cust_ledger:
                if p.get("entry_type") == "payment" and p.get("store_id") == sid:
                    alltime_payments.append(p)
    # All-time expenses
    alltime_expenses = [e for e in get_ledger("store", sid) if e.get("entry_type") == "expense"]

    # Sort and format sales and fees as separate sections
    sales_sorted = sorted(store_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)
    fees_sorted  = sorted(handling_fees, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)

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

    # Units sold: all customer/store_customer sales for this store
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

    # Totals for Sales, Fees, Grand Total (scoped)
    total_sales_only = sum(abs(s.get('quantity', 0) * s.get('unit_price', s.get('unit_cost', 0))) for s in sales_sorted)
    total_fees_only = sum(abs(f.get('amount', 0)) for f in fees_sorted)
    grand_total = total_sales_only + total_fees_only

    # EXPENSES (only expense entries, scoped)
    expenses = [e for e in sledger if e.get("entry_type") == "expense" and _between(e.get("date", ""), start, end)]

    expense_lines = []
    other_total = sum(abs(e.get("amount", 0)) for e in expenses)
    if expenses:
        expense_lines.append("• 🧾 Other Expenses")
        for e in expenses:
            expense_lines.append(f"   - {fmt_date(e.get('date', ''))}: {fmt_money(abs(e.get('amount', 0)), cur)}")
        expense_lines.append(f"📊 Total Other Expenses: {fmt_money(other_total, cur)}")
    total_all_expenses = other_total
    if expense_lines:
        expense_lines.append(f"\n📊 Total All Expenses: {fmt_money(total_all_expenses, cur)}")

    # INVENTORY BALANCE (all time, units and market value)
    stock_balance = defaultdict(int)
    for s in all_stockins:
        stock_balance[s.get("item_id")] += s.get("quantity", 0)
    for s in alltime_sales:
        stock_balance[s.get("item_id")] -= abs(s.get("quantity", 0))

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
            current_stock_lines.append(f"   - [{item}] {qty} units × {fmt_money(mp, cur)} = {fmt_money(val, cur)}")
            stock_value += val

    # ALL-TIME TOTALS for financial position
    all_sales_total = sum(abs(s.get('quantity', 0) * s.get('unit_price', s.get('unit_cost', 0))) for s in alltime_sales)
    all_fees_total = sum(abs(f.get('amount', 0)) for f in alltime_fees)
    all_payments_total = sum(p.get('amount', 0) for p in alltime_payments)
    all_expenses_total = sum(abs(e.get("amount", 0)) for e in alltime_expenses)
    alltime_balance = all_sales_total + all_fees_total - all_payments_total - all_expenses_total
    total_position = alltime_balance + stock_value

    lines = []
    if ctx["scope"] in ("full", "sales"):
        lines.append("🛒 Sales")
        lines += sales_lines
        lines.append("")
        lines.append("💸 Store Fees")
        lines += fee_lines
        lines.append("")
        lines.append("📦 Units Sold (by item):")
        lines += unit_summary
        lines.append(f"\n📊 Total Sales: {fmt_money(total_sales_only, cur)}")
        lines.append(f"📊 Total Store Fees: {fmt_money(total_fees_only, cur)}")
        lines.append(f"📊 Grand Total: {fmt_money(grand_total, cur)}\n")
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
            lines.append("• In :  ")
            lines += stockin_lines
        if current_stock_lines:
            lines.append("\n• Current Stock On Hand @ market: ")
            lines += current_stock_lines
        lines.append(f"\n📊 Stock Value: {fmt_money(stock_value, cur)}")
        lines.append("\n📊 Financial Position (ALL TIME)")
        lines.append(f"Balance (S + Fees − P − E): {fmt_money(alltime_balance, cur)}")
        lines.append(f"Inventory Value:     {fmt_money(stock_value, cur)}")
        lines.append("────────────────────────────────────")
        lines.append(f"Total Position:      {fmt_money(total_position, cur)}")

    nav = []
    if ctx["page"] > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="store_page_prev"))
    nav.append(InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))

    await update.callback_query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([nav]),
        parse_mode="Markdown"
    )
    return REPORT_PAGE

@require_unlock
async def paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == "store_page_next":
        context.user_data["page"] += 1
    elif update.callback_query.data == "store_page_prev":
        context.user_data["page"] = max(0, context.user_data["page"] - 1)
    return await show_report(update, context)

def register_store_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_store_report_menu, pattern="^rep_store$"))
    app.add_handler(CallbackQueryHandler(select_date_range, pattern="^store_sreport_"))
    app.add_handler(CallbackQueryHandler(choose_scope, pattern="^store_range_"))
    app.add_handler(CallbackQueryHandler(show_report, pattern="^store_scope_"))
    app.add_handler(CallbackQueryHandler(paginate, pattern="^store_page_"))
