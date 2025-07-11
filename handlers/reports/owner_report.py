import logging
from datetime import datetime
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_balance, get_ledger
from secure_db import secure_db

OWNER_ACCOUNT_ID = "POT"
(
    SHOW_POSITION,
) = range(1)

logger = logging.getLogger("owner_position")

def get_last_market_price(sales_entries, stockin_entries, item_id):
    relevant_sales = [e for e in sales_entries if e.get("item_id") == item_id]
    if relevant_sales:
        latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 0))
    relevant_stockins = [e for e in stockin_entries if e.get("item_id") == item_id]
    if relevant_stockins:
        latest = sorted(relevant_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", 0)
    return 0

def get_all_sales_payments(secure_db, get_ledger):
    all_sales = []
    all_payments = []
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            for e in get_ledger(acct_type, cust.doc_id):
                if e.get("entry_type") == "sale":
                    all_sales.append(e)
                elif e.get("entry_type") == "payment":
                    all_payments.append(e)
    return all_sales, all_payments

def get_all_payouts(secure_db, get_ledger):
    all_payouts = []
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") in ("payout", "payment_sent"):
                all_payouts.append(e)
    return all_payouts

def get_combined_inventory(secure_db, get_ledger):
    # Stock-ins: all stores and all partners (for all stores)
    stock_balance = defaultdict(int)
    all_stockins = []
    for store in secure_db.all("stores"):
        for e in get_ledger("store", store.doc_id):
            if e.get("entry_type") == "stockin":
                stock_balance[e.get("item_id")] += e.get("quantity", 0)
                all_stockins.append(e)
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "stockin" and e.get("store_id") is not None:
                stock_balance[e.get("item_id")] += e.get("quantity", 0)
                all_stockins.append(e)
    # Sales out: all customers/store_customers
    all_sales = []
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            for e in get_ledger(acct_type, cust.doc_id):
                if e.get("entry_type") == "sale":
                    stock_balance[e.get("item_id")] -= abs(e.get("quantity", 0))
                    all_sales.append(e)
    return stock_balance, all_sales, all_stockins

@require_unlock
async def show_owner_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()

    lines = []
    lines.append(f"📊 **Current Owner Position** 📊")

    # --- Sales & Payments (All Customers, All Time) ---
    all_sales, all_payments = get_all_sales_payments(secure_db, get_ledger)
    sales_summary = defaultdict(lambda: {"units": 0, "value": 0.0})
    for s in all_sales:
        iid = s.get("item_id", "?")
        units = abs(s.get("quantity", 0))
        value = abs(units * s.get("unit_price", s.get("unit_cost", 0)))
        sales_summary[iid]["units"] += units
        sales_summary[iid]["value"] += value
    total_sales_units = sum(d["units"] for d in sales_summary.values())
    total_sales_value = sum(d["value"] for d in sales_summary.values())

    lines.append(f"\n• Sales (All Customers, All Time):")
    if sales_summary:
        for iid, d in sales_summary.items():
            lines.append(f"   -  {iid}: {d['units']} units, {fmt_money(d['value'], 'USD')}")
        lines.append(f"   Total: {total_sales_units} units, {fmt_money(total_sales_value, 'USD')}")
    else:
        lines.append("   None")

    lines.append(f"\n• Payments (All Customers, All Time):")
    total_payments_value = sum(e.get("usd_amt", e.get("amount", 0)) for e in all_payments)
    if all_payments:
        lines.append(f"   -  {len(all_payments)} payments, {fmt_money(total_payments_value, 'USD')}")
    else:
        lines.append("   None")

    # --- Payouts (All Partners, All Time) ---
    all_payouts = get_all_payouts(secure_db, get_ledger)
    total_payouts_value = sum(abs(e.get("usd_amt", e.get("amount", 0))) for e in all_payouts)
    lines.append(f"\n• Payouts (All Partners, All Time):")
    if all_payouts:
        lines.append(f"   -  {len(all_payouts)} payouts, {fmt_money(total_payouts_value, 'USD')}")
    else:
        lines.append("   None")

    # --- Inventory (Combined All Stores, All Time) ---
    stock_balance, all_sales_for_price, all_stockins = get_combined_inventory(secure_db, get_ledger)
    lines.append(f"\n• Inventory (Combined All Stores, All Time):")
    inventory_lines = []
    total_market_value = 0
    for item_id, qty in stock_balance.items():
        if qty > 0:
            last_price = 0
            # Try last sale price, then last stockin price
            relevant_sales = [e for e in all_sales_for_price if e.get("item_id") == item_id]
            relevant_stockins = [e for e in all_stockins if e.get("item_id") == item_id]
            if relevant_sales:
                latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
                last_price = latest.get("unit_price", latest.get("unit_cost", 0))
            elif relevant_stockins:
                latest = sorted(relevant_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
                last_price = latest.get("unit_price", 0)
            item_value = qty * last_price
            total_market_value += item_value
            inventory_lines.append(f"   -  {item_id}: {qty} units × {fmt_money(last_price, 'USD')} = {fmt_money(item_value, 'USD')}")
    if inventory_lines:
        lines.extend(inventory_lines)
        lines.append(f"   Total Inventory Market Value: {fmt_money(total_market_value, 'USD')}")
    else:
        lines.append("   None")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="rep_owner")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])
    msg = "\n".join(lines)
    if update.callback_query:
        await update.callback_query.edit_message_text(msg[:4096], reply_markup=kb, parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(msg[:4096], reply_markup=kb, parse_mode="Markdown")
    return SHOW_POSITION

def register_owner_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_owner_position, pattern="^rep_owner$"))
    app.add_handler(CommandHandler("owner_position", show_owner_position))
