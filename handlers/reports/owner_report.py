import logging
from datetime import datetime
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_balance, get_ledger
from secure_db import secure_db

from handlers.reports.report_utils import (
    compute_store_inventory,
    compute_store_sales,
    compute_store_handling_fees,
    compute_store_payments,
    compute_store_expenses,
    compute_store_stockins,
)

OWNER_ACCOUNT_ID = "POT"
(
    SHOW_POSITION,
) = range(1)

logger = logging.getLogger("owner_position")

def owner_report_diagnostic(start, end, secure_db, get_ledger):
    print("\n==== OWNER REPORT DIAGNOSTIC ====")
    print(f"DATE RANGE: {start} to {end}")

    inventory = compute_store_inventory(secure_db, get_ledger)
    sales = compute_store_sales(secure_db, get_ledger, start, end)
    fees = compute_store_handling_fees(secure_db, get_ledger, start, end)
    payments = compute_store_payments(secure_db, get_ledger, start=start, end=end)
    expenses = compute_store_expenses(secure_db, get_ledger, start, end)
    stockins = compute_store_stockins(secure_db, get_ledger, start, end)

    print("[Store Inventories]")
    for sid, items in inventory.items():
        print(f"  Store {sid}: {items}")

    print("[Store Sales]")
    for sid, items in sales.items():
        print(f"  Store {sid}: {dict((item, len(entries)) for item, entries in items.items())}")

    print("[Handling Fees]")
    for sid, items in fees.items():
        print(f"  Store {sid}: {dict((item, len(entries)) for item, entries in items.items())}")

    print("[Payments]")
    for sid, plist in payments.items():
        print(f"  Store {sid}: {len(plist)} payments")

    print("[Expenses]")
    for sid, elist in expenses.items():
        print(f"  Store {sid}: {len(elist)} expenses")

    print("[Stock-ins]")
    for sid, slist in stockins.items():
        print(f"  Store {sid}: {len(slist)} stock-ins")

    print("==== END OWNER REPORT DIAGNOSTIC ====\n")

@require_unlock
async def show_owner_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    cash = get_balance("owner", OWNER_ACCOUNT_ID)
    cash_str = fmt_money(cash, "USD")

    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.now()

    inventory = compute_store_inventory(secure_db, get_ledger)
    sales = compute_store_sales(secure_db, get_ledger, start, end)
    fees = compute_store_handling_fees(secure_db, get_ledger, start, end)
    payments = compute_store_payments(secure_db, get_ledger, start=start, end=end)
    expenses = compute_store_expenses(secure_db, get_ledger, start, end)
    stockins = compute_store_stockins(secure_db, get_ledger, start, end)

    lines = []
    lines.append(f"📊 **Current Owner Position** 📊")
    lines.append(f"\n• Cash Balance: {cash_str}")

    for store in secure_db.all("stores"):
        sid = store.doc_id
        sname = store.get("name")
        cur = store.get("currency", "USD")
        lines.append(f"\n🏬 **Store: {sname} ({cur})**")

        # Inventory
        inv_items = inventory.get(sid, {})
        inv_line = " / ".join([f"{item}: {qty} units" for item, qty in inv_items.items() if qty > 0]) or "No inventory"
        lines.append(f"  • Inventory: {inv_line}")

        # Sales
        sales_items = sales.get(sid, {})
        sales_line = []
        sales_total = 0
        for item, entries in sales_items.items():
            units = sum(abs(e.get("quantity", 0)) for e in entries)
            total = sum(abs(e.get("quantity", 0) * e.get("unit_price", e.get("unit_cost", 0))) for e in entries)
            sales_line.append(f"{item}: {units} units, {fmt_money(total, cur)}")
            sales_total += total
        lines.append(f"  • Sales: {' / '.join(sales_line) if sales_line else 'None'} (Total: {fmt_money(sales_total, cur)})")

        # Handling Fees
        fees_items = fees.get(sid, {})
        fee_line = []
        fee_total = 0
        for item, entries in fees_items.items():
            total = sum(abs(e.get("amount", 0)) for e in entries)
            fee_line.append(f"{item}: {fmt_money(total, cur)}")
            fee_total += total
        lines.append(f"  • Handling Fees: {' / '.join(fee_line) if fee_line else 'None'} (Total: {fmt_money(fee_total, cur)})")

        # Payments
        payment_list = payments.get(sid, [])
        pay_total = sum(p.get("amount", 0) for p in payment_list)
        pay_total_usd = sum(p.get("usd_amt", 0) for p in payment_list)
        lines.append(f"  • Payments: {len(payment_list)} payments (Total: {fmt_money(pay_total, cur)}, USD: {fmt_money(pay_total_usd, 'USD')})")

        # Expenses
        expense_list = expenses.get(sid, [])
        exp_total = sum(abs(e.get("amount", 0)) for e in expense_list)
        lines.append(f"  • Expenses: {len(expense_list)} entries (Total: {fmt_money(exp_total, cur)})")

        # Stock-ins
        stockin_list = stockins.get(sid, [])
        stockin_line = []
        for e in stockin_list:
            stockin_line.append(f"[{e.get('item_id', '?')}] {e.get('quantity', 0)} on {fmt_date(e.get('date', ''))}")
        lines.append(f"  • Stock-ins: {'; '.join(stockin_line) if stockin_line else 'None'}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="rep_owner")],
        [InlineKeyboardButton("🩺 Diagnostics", callback_data="owner_diag")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])

    # Terminal diagnostics
    owner_report_diagnostic(start, end, secure_db, get_ledger)

    # Send message
    msg = "\n".join(lines)
    if update.callback_query:
        await update.callback_query.edit_message_text(msg[:4096], reply_markup=kb, parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(msg[:4096], reply_markup=kb, parse_mode="Markdown")
    return SHOW_POSITION

def register_owner_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_owner_position, pattern="^rep_owner$"))
    app.add_handler(CommandHandler("owner_position", show_owner_position))
