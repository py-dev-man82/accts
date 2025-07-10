import logging
from datetime import datetime
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_balance, get_ledger
from secure_db import secure_db

# Constants
OWNER_ACCOUNT_ID = "POT"

# Conversation state (single state)
(
    SHOW_POSITION,
) = range(1)

logger = logging.getLogger("owner_position")

@require_unlock
async def show_owner_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Display current net position: cash balance, inventory valuation, and store levels
    """
    # Acknowledge callback or command
    if update.callback_query:
        await update.callback_query.answer()
    # 1️ Cash position
    cash = get_balance("owner", OWNER_ACCOUNT_ID)
    cash_str = fmt_money(cash, "USD")

    # 2️ Partner Inventory Valuation
    partner_stock: dict[str, int] = defaultdict(int)
    # Aggregate stock-in and stock-out from partner ledgers
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "stockin":
                partner_stock[e.get("item_id", "?")] += e.get("quantity", 0)
            elif e.get("entry_type") == "sale":
                partner_stock[e.get("item_id", "?")] -= abs(e.get("quantity", 0))
    # Collect all partner sales for pricing
    all_partner_sales = [
        e
        for partner in secure_db.all("partners")
        for e in get_ledger("partner", partner.doc_id)
        if e.get("entry_type") == "sale"
    ]
    def get_last_price(item_id: str) -> float:
        sales = [e for e in all_partner_sales if e.get("item_id") == item_id]
        if sales:
            latest = sorted(
                sales,
                key=lambda x: (x.get("date", ""), x.get("timestamp", "")),
                reverse=True
            )[0]
            return latest.get("unit_price", 0.0)
        return 0.0

    stock_value = sum(
        qty * get_last_price(item)
        for item, qty in partner_stock.items()
        if qty > 0
    )
    inv_str = fmt_money(stock_value, "USD")

    # 3️ Store Inventory Levels
    store_stock: dict[str, int] = defaultdict(int)
    for store in secure_db.all("stores"):
        for e in get_ledger("store", store.doc_id):
            if e.get("entry_type") == "stockin":
                store_stock[e.get("item_id", "?")] += e.get("quantity", 0)
            elif e.get("entry_type") == "sale":
                store_stock[e.get("item_id", "?")] -= abs(e.get("quantity", 0))
    # Format store inventory lines
    if store_stock:
        store_lines = [f"• {item}: {qty} units" for item, qty in store_stock.items()]
    else:
        store_lines = ["No store inventory."]
    store_lines_str = "\n".join(store_lines)

    # Build output text
    text = (
        f"📊 **Current Owner Position** 📊\n\n"
        f"• Cash Balance: {cash_str}\n"
        f"• Inventory Value: {inv_str}\n\n"
        f"• Store Inventory Levels:\n{store_lines_str}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="owner_pos")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])

    # Send or edit message
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    return SHOW_POSITION

def register_owner_position(app):
    # Callback and command to show owner position
    app.add_handler(CallbackQueryHandler(show_owner_position, pattern="^owner_pos$"))
    app.add_handler(CommandHandler("owner_position", show_owner_position))
