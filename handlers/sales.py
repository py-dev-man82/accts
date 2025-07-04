# handlers/sales.py

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

# State constants for Sales flow
(
    SALE_SEL_CUST,
    SALE_SEL_STORE,
    SALE_SEL_ITEM,
    SALE_ASK_QTY,
    SALE_ASK_PRICE,
    SALE_ASK_NOTE,
    SALE_CONFIRM
) = range(7)

def register_sales_handlers(app):
    sales_conv = ConversationHandler(
        entry_points=[
            CommandHandler('add_sale', start_sale),
        ],
        states={
            SALE_SEL_CUST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_sale_customer)
            ],
            SALE_SEL_STORE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_sale_store)
            ],
            SALE_SEL_ITEM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_sale_item)
            ],
            SALE_ASK_QTY: [
                MessageHandler(filters.Regex(r'^\d+$'), ask_sale_quantity)
            ],
            SALE_ASK_PRICE: [
                MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_sale_price)
            ],
            SALE_ASK_NOTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_sale_note)
            ],
            SALE_CONFIRM: [
                CallbackQueryHandler(finalize_sale, pattern='^(confirm_sale|cancel_sale)$')
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_sale)],
        allow_reentry=True
    )
    app.add_handler(sales_conv)

# --- Handlers (stubs) ---

async def start_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter customer ID for this sale:")
    return SALE_SEL_CUST

async def select_sale_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sale_customer'] = update.message.text.strip()
    await update.message.reply_text("Enter store ID:")
    return SALE_SEL_STORE

async def select_sale_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sale_store'] = update.message.text.strip()
    await update.message.reply_text("Enter item ID:")
    return SALE_SEL_ITEM

async def select_sale_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sale_item'] = update.message.text.strip()
    await update.message.reply_text("Enter quantity (integer):")
    return SALE_ASK_QTY

async def ask_sale_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sale_qty'] = int(update.message.text.strip())
    await update.message.reply_text("Enter unit price (e.g. 19.99):")
    return SALE_ASK_PRICE

async def ask_sale_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sale_price'] = float(update.message.text.strip())
    await update.message.reply_text("Enter an optional note or type 'none':")
    return SALE_ASK_NOTE

async def ask_sale_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    context.user_data['sale_note'] = note if note.lower() != 'none' else ''
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data='confirm_sale'),
        InlineKeyboardButton("❌ Cancel", callback_data='cancel_sale')
    ]])
    summary = (
        f"Sale summary:\n"
        f"Customer: {context.user_data['sale_customer']}\n"
        f"Store:    {context.user_data['sale_store']}\n"
        f"Item:     {context.user_data['sale_item']}\n"
        f"Qty:      {context.user_data['sale_qty']}\n"
        f"Price:    {context.user_data['sale_price']:.2f}\n"
        f"Note:     {context.user_data['sale_note'] or '<none>'}"
    )
    await update.message.reply_text(summary, reply_markup=kb)
    return SALE_CONFIRM

async def finalize_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == 'confirm_sale':
        # Insert into DB
        secure_db.insert('customer_sales', {
            'customer_id': context.user_data['sale_customer'],
            'store_id':    context.user_data['sale_store'],
            'item_id':     context.user_data['sale_item'],
            'qty':         context.user_data['sale_qty'],
            'unit_price':  context.user_data['sale_price'],
            'note':        context.user_data['sale_note'],
            'created_at':  datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text("✅ Sale recorded.")
    else:
        await update.callback_query.edit_message_text("❌ Sale cancelled.")
    return ConversationHandler.END

async def cancel_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sale entry cancelled.")
    return ConversationHandler.END
