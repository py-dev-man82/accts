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
    compute_partner_sales,
    compute_payouts,
    compute_store_inventory,
    compute_partner_inventory,
)

OWNER_ACCOUNT_ID = "POT"
(
    SHOW_POSITION,
) = range(1)

def get_last_market_price(all_sales, all_stockins, item_id):
    # Use all sales and stockins from ALL stores for best market value accuracy
    relevant_sales = [e for e in all_sales if e.get("item_id") == item_id]
    if relevant_sales:
        latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 1.0))
    relevant_stockins = [e for e in all_stockins if e.get("item_id") == item_id]
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

    # --- Aggregate owner inventory by item across all stores ---
    owner_inventory_by_item = defaultdict(int)
    for store_id, items in store_inventory.items():
        for item_id, qty in items.items():
            owner_inventory_by_item[item_id] += qty

    # --- Gather all sales and stockins for price lookup ---
    all_sales_entries = []
    all_stockin_entries = []
    # Collect all sales (from all store/customer ledgers if you wish)
    for store_id, item_sales in compute_store_sales(secure_db, get_ledger).items():
        for sales_list in item_sales.values():
            all_sales_entries.extend(sales_list)
    # Optionally, add partner/customer sales as well if relevant for market
    for cust_sales in customer_sales.values():
        for sales_list in cust_sales.values():
            all_sales_entries.extend(sales_list)
    for partner_sales_dict in partner_sales.values():
        for sales_list in partner_sales_dict.values():
            all_sales_entries.extend(sales_list)
    # Collect all stockins (from all stores)
    for store_id, stockins in compute_store_inventory(secure_db, get_ledger).items():
        for item_id, qty in stockins.items():
            # You might want to get entries not just counts here; adjust as needed for your data
            pass # if you have stockin entry lists elsewhere, gather here

    # --- Calculate market value by item ---
    total_owner_inventory_value = 0
    inventory_lines = []
    for item_id, qty in owner_inventory_by_item.items():
        if qty > 0:
            price = get_last_market_price(all_sales_entries, [], item_id)
            value = qty * price
            total_owner_inventory_value += value
            inventory_lines.append(f"    - {item_id}: {qty} units × {fmt_money(price, 'USD')} = {fmt_money(value, 'USD')}")
    if not inventory_lines:
        inventory_lines.append("    (No inventory)")

    # --- Partner inventory value and reconciliation ---
    partner_inventory_value = 0
    for partner_id, items in partner_inventory.items():
        for item_id, qty in items.items():
            price = get_last_market_price(all_sales_entries, [], item_id)
            partner_inventory_value += qty * price

    # --- Net position ---
    net_position = owner_cash_position + total_owner_inventory_value

    # --- Output ---
    lines = []
    lines.append(f"📊 **Owner Financial Position** 📊")
    lines.append(f"• Cash Position (POT): {fmt_money(owner_cash_position, 'USD')}")
    lines.append(f"• Owner Inventory (by item):")
    lines += inventory_lines
    lines.append(f"• Owner Inventory Total Market Value: {fmt_money(total_owner_inventory_value, 'USD')}")
    lines.append(f"• Partner Inventory Value: {fmt_money(partner_inventory_value, 'USD')}")
    lines.append(f"• Net Position (Cash + Inventory): {fmt_money(net_position, 'USD')}")

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