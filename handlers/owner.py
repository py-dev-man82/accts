# handlers/owner.py

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)
from datetime import datetime
from secure_db import secure_db
from handlers.utils import require_unlock

# State constants
(
    O_PRICE_SELECT,
    O_PRICE_INPUT,
    O_PRICE_CONFIRM,
    O_POT_ACTION,
    O_POT_INPUT,
    O_POT_NOTE,
    O_POT_CONFIRM,
) = range(7)

# ─────────────────────────────────────────────────────────────
# Self-Healing Schema Check
# ─────────────────────────────────────────────────────────────
def ensure_owner_schema():
    # Touch 'owner_adjustments' to auto-create if missing
    _ = secure_db.all('owner_adjustments')

    # Add current_price field to items if missing
    for item in secure_db.all('items'):
        if 'current_price' not in item:
            secure_db.update('items', {'current_price': 0.0}, [item.doc_id])
            logging.info(f"[Owner] Added current_price=0.0 to item {item.get('name', '')}")

# Run schema check on import
ensure_owner_schema()

# ─────────────────────────────────────────────────────────────
# Owner Menu
# ─────────────────────────────────────────────────────────────
async def show_owner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing owner menu")
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Overview", callback_data="owner_overview")],
        [InlineKeyboardButton("💲 Set Market Prices", callback_data="owner_set_prices")],
        [InlineKeyboardButton("🏦 Adjust POT Balance", callback_data="owner_adjust_pot")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
    ])
    await update.callback_query.edit_message_text(
        "👑 Owner: choose an action", reply_markup=kb
    )

# ─────────────────────────────────────────────────────────────
# Overview
# ─────────────────────────────────────────────────────────────
@require_unlock
async def show_owner_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    # POT Balance
    pot_in = sum(r['usd_amt'] for r in secure_db.all('customer_payments'))
    pot_out = sum(r['usd_amt'] for r in secure_db.all('partner_payouts'))
    adjustments = sum(r['amount'] for r in secure_db.all('owner_adjustments'))
    pot_balance = pot_in - pot_out + adjustments

    # Store Inventory (at current prices)
    store_inventory = 0
    for store in secure_db.all('stores'):
        for sale in secure_db.all('sales'):
            if sale['store_id'] == store.doc_id:
                item = secure_db.table('items').get(doc_id=sale['item_id'])
                if item:
                    price = item.get('current_price', 0.0)
                    store_inventory += sale['quantity'] * price

    owner_cash = pot_balance + store_inventory

    # Partners Position
    partners_cash = 0
    for partner in secure_db.all('partners'):
        partner_sales = sum(r['usd_amt'] for r in secure_db.all('sales') if r.get('partner_id') == partner.doc_id)
        partner_payouts = sum(r['usd_amt'] for r in secure_db.all('partner_payouts') if r['partner_id'] == partner.doc_id)
        partner_balance = partner_sales - partner_payouts

        partner_inventory = 0
        for inv in secure_db.all('partner_inventory'):
            if inv['partner_id'] == partner.doc_id:
                item = secure_db.table('items').get(doc_id=inv['item_id'])
                if item:
                    price = item.get('current_price', 0.0)
                    partner_inventory += inv['quantity'] * price

        partners_cash += partner_balance + partner_inventory

    # Reconciliation (Cash)
    reconciliation = owner_cash - partners_cash
    rec_status = "✅ Balanced" if reconciliation >= 0 else "🔴 Unbalanced"

    # Stock Reconciliation
    total_owner_items = sum(inv['quantity'] for inv in secure_db.all('sales'))
    total_partner_items = sum(inv['quantity'] for inv in secure_db.all('partner_inventory'))
    stock_status = "✅ Balanced" if total_owner_items == total_partner_items else "⚠️ Unbalanced"

    text = (
        f"📊 *Owner Overview*\n"
        f"──────────────────────────────\n"
        f"🏦 POT Balance:          ${pot_balance:,.2f}\n"
        f"🏪 Stores Inventory:     ${store_inventory:,.2f}\n"
        f"──────────────────────────────\n"
        f"💵 Owner Cash:           ${owner_cash:,.2f}\n"
        f"🤝 Partners Position:    ${partners_cash:,.2f}\n"
        f"──────────────────────────────\n"
        f"⚖️ Cash Reconciliation:  {rec_status}\n"
        f"📦 Stock Reconciliation: {stock_status}\n"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="owner_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

# ─────────────────────────────────────────────────────────────
# Set Market Prices
# ─────────────────────────────────────────────────────────────
@require_unlock
async def set_market_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    items = secure_db.all('items')
    if not items:
        await update.callback_query.edit_message_text(
            "No items found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="owner_menu")]])
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{item['name']} (${item.get('current_price', 0):.2f})", callback_data=f"price_item_{item.doc_id}")
        for item in items
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("📦 Select an item to update:", reply_markup=kb)
    return O_PRICE_SELECT

async def get_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    item_id = int(update.callback_query.data.split("_")[-1])
    context.user_data['price_item_id'] = item_id
    item = secure_db.table('items').get(doc_id=item_id)
    context.user_data['price_item_name'] = item['name']
    await update.callback_query.edit_message_text(
        f"{item['name']}\n───────────────\nCurrent price: ${item.get('current_price', 0):.2f}\n\nEnter new market price:"
    )
    return O_PRICE_INPUT

async def confirm_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
        assert price > 0
    except:
        await update.message.reply_text("Invalid price. Enter a positive number:")
        return O_PRICE_INPUT

    context.user_data['new_price'] = price
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="price_conf_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="price_conf_no")]
    ])
    await update.message.reply_text(
        f"Confirm setting *{context.user_data['price_item_name']}* market price to ${price:.2f}?",
        reply_markup=kb, parse_mode="Markdown"
    )
    return O_PRICE_CONFIRM

@require_unlock
async def save_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "price_conf_yes":
        secure_db.update('items', {
            'current_price': context.user_data['new_price']
        }, [context.user_data['price_item_id']])
        await update.callback_query.edit_message_text(
            f"✅ Market price updated to ${context.user_data['new_price']:.2f}.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="owner_menu")]])
        )
    else:
        await update.callback_query.edit_message_text(
            "❌ Cancelled. No changes made.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="owner_menu")]])
        )
    return ConversationHandler.END

# ─────────────────────────────────────────────────────────────
# Adjust POT Balance (same as before)
# ─────────────────────────────────────────────────────────────
# ... (keep existing Adjust POT functions here unchanged)

# ─────────────────────────────────────────────────────────────
# Register Handlers
# ─────────────────────────────────────────────────────────────
def register_owner_handlers(app):
    app.add_handler(CallbackQueryHandler(show_owner_menu, pattern="^owner_menu$"))
    app.add_handler(CallbackQueryHandler(show_owner_overview, pattern="^owner_overview$"))
    app.add_handler(CallbackQueryHandler(set_market_prices, pattern="^owner_set_prices$"))
    # ... plus Adjust POT Balance handlers ...