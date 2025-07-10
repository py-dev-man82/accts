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
    """
    Returns last sale price for item_id if any, otherwise last stock-in price.
    """
    relevant_sales = [e for e in sales_entries if e.get("item_id") == item_id]
    if relevant_sales:
        latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 0))
    relevant_stockins = [e for e in stockin_entries if e.get("item_id") == item_id]
    if relevant_stockins:
        latest = sorted(relevant_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", 0)
    return 0

def get_store_inventory(secure_db, get_ledger, store_doc_id):
    # 1. All stock-ins (store + partner)
    stock_balance = defaultdict(int)
    stockin_entries = []
    # Store ledger stock-ins
    for e in get_ledger("store", store_doc_id):
        if e.get("entry_type") == "stockin":
            stock_balance[e.get("item_id")] += e.get("quantity", 0)
            stockin_entries.append(e)
    # Partner ledger stock-ins (where store_id matches this store)
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "stockin" and e.get("store_id") == store_doc_id:
                stock_balance[e.get("item_id")] += e.get("quantity", 0)
                stockin_entries.append(e)
    # 2. All sales out (from customer/store_customer ledgers whose name matches this store)
    store_name = secure_db.table("stores").get(doc_id=store_doc_id).get("name")
    store_customer_ids = [c.doc_id for c in secure_db.all("customers") if c.get("name") == store_name]
    sales_entries = []
    for cust_id in store_customer_ids:
        for acct_type in ["customer", "store_customer"]:
            for e in get_ledger(acct_type, cust_id):
                if e.get("entry_type") == "sale":
                    stock_balance[e.get("item_id")] -= abs(e.get("quantity", 0))
                    sales_entries.append(e)
    return stock_balance, sales_entries, stockin_entries

@require_unlock
async def show_owner_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()

    lines = []
    lines.append(f"📊 **Current Owner Position** 📊")

    for store in secure_db.all("stores"):
        sid = store.doc_id
        sname = store.get("name")
        cur = store.get("currency", "USD")
        lines.append(f"\n🏬 **Store: {sname} ({cur})**")
        stock_balance, sales_entries, stockin_entries = get_store_inventory(secure_db, get_ledger, sid)
        inventory_lines = []
        total_market_value = 0
        for item_id, qty in stock_balance.items():
            if qty > 0:
                last_price = get_last_market_price(sales_entries, stockin_entries, item_id)
                item_value = qty * last_price
                total_market_value += item_value
                inventory_lines.append(f"   - [{item_id}] {qty} units × {fmt_money(last_price, cur)} = {fmt_money(item_value, cur)}")
        if inventory_lines:
            lines.append("  • Inventory:")
            lines.extend(inventory_lines)
            lines.append(f"    Total Market Value: {fmt_money(total_market_value, cur)}")
        else:
            lines.append("  • Inventory: No inventory")
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
