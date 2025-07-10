import logging
from datetime import datetime
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_balance, get_ledger
from secure_db import secure_db

# Shared report utilities
from handlers.reports.report_utils import (
    compute_store_inventory,
    compute_store_sales,
    compute_partner_sales,
    compute_payouts,
)

OWNER_ACCOUNT_ID = "POT"

(
    SHOW_POSITION,
) = range(1)

logger = logging.getLogger("owner_position")

def owner_report_diagnostic(start, end, secure_db, get_ledger):
    print("\n==== OWNER REPORT DIAGNOSTIC ====")
    print(f"DATE RANGE: {start} to {end}")

    # Store Inventory
    store_inventory = compute_store_inventory(secure_db, get_ledger)
    print("[Store Inventories]")
    for store_id, items in store_inventory.items():
        print(f"  Store {store_id}: {items}")

    # Store Sales
    store_sales = compute_store_sales(secure_db, get_ledger)
    print("[Store Sales]")
    for store_id, items in store_sales.items():
        print(f"  Store {store_id}: {items}")

    # Partner Sales
    partner_sales = compute_partner_sales(secure_db, get_ledger)
    print("[Partner Sales]")
    for partner_id, items in partner_sales.items():
        print(f"  Partner {partner_id}: {items}")

    # Payouts
    payouts = compute_payouts(secure_db, get_ledger)
    print(f"[Payout Entries] ({len(payouts)})")
    for entry in payouts[:10]:  # limit for display
        print(f"  {entry}")

    print("==== END OWNER REPORT DIAGNOSTIC ====\n")

@require_unlock
async def show_owner_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Display current net position: cash balance, inventory valuation, and store levels.
    Print diagnostics in terminal.
    """
    if update.callback_query:
        await update.callback_query.answer()
    cash = get_balance("owner", OWNER_ACCOUNT_ID)
    cash_str = fmt_money(cash, "USD")

    # Use shared function for store inventory
    store_inventory = compute_store_inventory(secure_db, get_ledger)
    store_lines = []
    for store_id, items in store_inventory.items():
        line = f"Store {store_id}: " + ", ".join(f"{item}: {qty} units" for item, qty in items.items())
        store_lines.append(line)
    if not store_lines:
        store_lines = ["No store inventory."]
    store_lines_str = "\n".join(store_lines)

    # (Sample: still using partner logic inline for valuation, but you could refactor this as well)
    partner_stock: dict[str, int] = defaultdict(int)
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "stockin":
                partner_stock[e.get("item_id", "?")] += e.get("quantity", 0)
            elif e.get("entry_type") == "sale":
                partner_stock[e.get("item_id", "?")] -= abs(e.get("quantity", 0))
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

    text = (
        f"📊 **Current Owner Position** 📊\n\n"
        f"• Cash Balance: {cash_str}\n"
        f"• Inventory Value: {inv_str}\n\n"
        f"• Store Inventory Levels:\n{store_lines_str}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="rep_owner")],
        [InlineKeyboardButton("🩺 Diagnostics", callback_data="owner_diag")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])

    # Print diagnostics to terminal/log
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.now()
    owner_report_diagnostic(start, end, secure_db, get_ledger)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    return SHOW_POSITION

@require_unlock
async def show_owner_diagnostics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.now()
    # Show raw diagnostics in the Telegram chat
    store_inventory = compute_store_inventory(secure_db, get_ledger)
    store_lines = []
    for store_id, items in store_inventory.items():
        line = f"Store {store_id}: " + ", ".join(f"{item}: {qty} units" for item, qty in items.items())
        store_lines.append(line)
    text = "🩺 **Diagnostics**\n\n[Store Inventories]\n" + "\n".join(store_lines)
    await update.callback_query.edit_message_text(
        text[:4096],  # Telegram message size limit
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="rep_owner")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        ]),
        parse_mode="Markdown"
    )

def register_owner_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_owner_position, pattern="^rep_owner$"))
    app.add_handler(CallbackQueryHandler(show_owner_diagnostics, pattern="^owner_diag$"))
    app.add_handler(CommandHandler("owner_position", show_owner_position))
