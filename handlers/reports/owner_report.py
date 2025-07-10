import logging
from collections import defaultdict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money
from handlers.ledger import get_balance, get_ledger
from secure_db import secure_db

from handlers.reports.report_utils import (
    compute_customer_sales,
    compute_customer_payments,
    compute_partner_sales,      # must exist in report_utils
    compute_payouts,
    compute_store_inventory,
    compute_partner_inventory,  # must exist in report_utils
)

OWNER_ACCOUNT_ID = "POT"
(
    SHOW_POSITION,
) = range(1)

def get_last_market_price(sales_entries, stockin_entries, item_id):
    # For now, just fallback to 1.0 if not available
    relevant_sales = [e for e in sales_entries if e.get("item_id") == item_id]
    if relevant_sales:
        latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 1.0))
    relevant_stockins = [e for e in stockin_entries if e.get("item_id") == item_id]
    if relevant_stockins:
        latest = sorted(relevant_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", 1.0)
    return 1.0

@require_unlock
async def show_owner_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()

    # Pull all data (all time)
    customer_sales = compute_customer_sales(secure_db, get_ledger)
    customer_payments = compute_customer_payments(secure_db, get_ledger)
    partner_sales = compute_partner_sales(secure_db, get_ledger)
    payouts = compute_payouts(secure_db, get_ledger)
    store_inventory = compute_store_inventory(secure_db, get_ledger)
    partner_inventory = compute_partner_inventory(secure_db, get_ledger)

    # --- Cash position (POT): total USD received from customers - total payouts sent ---
    cash_in = 0
    for cust_id, payment_list in customer_payments.items():
        for p in payment_list:
            cash_in += p.get('usd_amt', 0)
    cash_out = sum(abs(p.get('amount', 0)) for p in payouts)
    owner_cash_position = cash_in - cash_out

    # --- Owner inventory value ---
    owner_inventory_value = 0
    for store_id, items in store_inventory.items():
        for item_id, qty in items.items():
            # Optionally: get last market price per item using all available data (improve as needed)
            price = 1.0  # fallback
            owner_inventory_value += qty * price

    # --- Partner inventory value ---
    partner_inventory_value = 0
    for partner_id, items in partner_inventory.items():
        for item_id, qty in items.items():
            price = 1.0  # fallback
            partner_inventory_value += qty * price

    # --- Inventory reconciliation ---
    total_store_units = sum(sum(items.values()) for items in store_inventory.values())
    total_partner_units = sum(sum(items.values()) for items in partner_inventory.values())
    total_inventory_units = total_store_units + total_partner_units

    # (Optional) Expected inventory: total stock-ins minus total sales (customer + partner)
    # You can implement this logic for deep reconciliation

    # --- Net position ---
    net_position = owner_cash_position + owner_inventory_value

    # --- Output ---
    lines = []
    lines.append(f"📊 **Owner Financial Position** 📊")
    lines.append(f"• Cash Position (POT): {fmt_money(owner_cash_position, 'USD')}")
    lines.append(f"• Owner Inventory Value: {fmt_money(owner_inventory_value, 'USD')}")
    lines.append(f"• Partner Inventory Value: {fmt_money(partner_inventory_value, 'USD')}")
    lines.append(f"• Total Inventory Units (store+partner): {total_inventory_units}")
    lines.append(f"• Net Position (Cash + Inventory): {fmt_money(net_position, 'USD')}")
    lines.append("\n[Details on customer sales, partner sales, payouts, etc. can be shown below if desired]")

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