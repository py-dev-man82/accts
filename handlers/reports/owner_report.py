import logging
from datetime import datetime
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_balance, get_ledger
from secure_db import secure_db

from handlers.reports.report_utils import (
    compute_store_sales,
    compute_store_stockins,
)

OWNER_ACCOUNT_ID = "POT"
(
    SHOW_POSITION,
) = range(1)

logger = logging.getLogger("owner_position")

def get_last_market_price(sales_entries, stockin_entries, item_id):
    """
    Returns last sale price for item_id if any, otherwise last stock-in price.
    """
    # Find last sale price
    relevant_sales = [e for e in sales_entries if e.get("item_id") == item_id]
    if relevant_sales:
        latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 0))
    # Otherwise, last stock-in price
    relevant_stockins = [e for e in stockin_entries if e.get("item_id") == item_id]
    if relevant_stockins:
        latest = sorted(relevant_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", 0)
    return 0

@require_unlock
async def show_owner_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()

    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.now()

    # All-time (no date filter)
    stockins_all = compute_store_stockins(secure_db, get_ledger)  # dict[store_id] = [entries...]
    sales_all = compute_store_sales(secure_db, get_ledger)        # dict[store_id][item_id] = [entries...]

    lines = []
    lines.append(f"📊 **Current Owner Position** 📊")

    for store in secure_db.all("stores"):
        sid = store.doc_id
        sname = store.get("name")
        cur = store.get("currency", "USD")
        lines.append(f"\n🏬 **Store: {sname} ({cur})**")
        # Inventory balance by item
        stock_balance = defaultdict(int)
        # Add up all stock-ins for this store
        for s in stockins_all.get(sid, []):
            stock_balance[s.get("item_id")] += s.get("quantity", 0)
        # Subtract all sales for this store
        store_sales_items = sales_all.get(sid, {})
        all_sales_entries = []
        for item_id, item_sales in store_sales_items.items():
            all_sales_entries.extend(item_sales)
            for s in item_sales:
                stock_balance[s.get("item_id")] -= abs(s.get("quantity", 0))
        # Prepare inventory lines and market value calculation
        inventory_lines = []
        total_market_value = 0
        for item_id, qty in stock_balance.items():
            if qty > 0:
                # Find last price
                last_price = get_last_market_price(all_sales_entries, stockins_all.get(sid, []), item_id)
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
