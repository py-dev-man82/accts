# handlers/stockin.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from datetime import datetime
from tinydb import Query
from secure_db import secure_db

# State constants for Stock-In flow
(
    SI_PARTNER,
    SI_ITEM,
    SI_QUANTITY,
    SI_COST,
    SI_CONFIRM,
) = range(5)

# Register Stock-In handlers
def register_stockin_handlers(app):
    stockin_conv = ConversationHandler(
        entry_points=[CommandHandler('add_stockin', start_stockin)],
        states={
            SI_PARTNER: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_stockin_partner)],
            SI_ITEM:    [MessageHandler(filters.TEXT & ~filters.COMMAND, select_stockin_item)],
            SI_QUANTITY: [MessageHandler(filters.Regex(r'^\d+$'), ask_stockin_quantity)],
            SI_COST:     [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_stockin_cost)],
            SI_CONFIRM:  [CallbackQueryHandler(finalize_stockin, pattern='^(confirm_stockin|cancel_stockin)$')],
        },
        fallbacks=[CommandHandler('cancel', cancel_stockin)],
        allow_reentry=True
    )
    app.add_handler(stockin_conv)

# --- Handlers ---
async def start_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter partner ID for stock-in:")
    return SI_PARTNER

async def select_stockin_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['stockin_partner'] = update.message.text.strip()
    await update.message.reply_text("Enter item ID:")
    return SI_ITEM

async def select_stockin_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['stockin_item'] = update.message.text.strip()
    await update.message.reply_text("Enter quantity (integer):")
    return SI_QUANTITY

async def ask_stockin_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['stockin_qty'] = int(update.message.text.strip())
    await update.message.reply_text("Enter cost per unit (e.g. 12.50):")
    return SI_COST

async def ask_stockin_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['stockin_cost'] = float(update.message.text.strip())
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data='confirm_stockin'),
        InlineKeyboardButton("❌ Cancel", callback_data='cancel_stockin')
    ]])
    qty = context.user_data['stockin_qty']
    cost = context.user_data['stockin_cost']
    summary = (
        f"Stock-In summary:\n"
        f"Partner: {context.user_data['stockin_partner']}\n"
        f"Item:    {context.user_data['stockin_item']}\n"
        f"Qty:     {qty}\n"
        f"Cost:    {cost:.2f} each"
    )
    await update.message.reply_text(summary, reply_markup=kb)
    return SI_CONFIRM

async def finalize_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == 'confirm_stockin':
        secure_db.insert('partner_inventory', {
            'partner_id': context.user_data['stockin_partner'],
            'item_id':    context.user_data['stockin_item'],
            'qty':        context.user_data['stockin_qty'],
            'cost':       context.user_data['stockin_cost'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text("✅ Stock-in recorded.")
    else:
        await update.callback_query.edit_message_text("❌ Stock-in cancelled.")
    return ConversationHandler.END

async def cancel_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END
