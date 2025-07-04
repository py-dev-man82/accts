# handlers/sales.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes
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

# Register Sales handlers
def register_sales_handlers(app):
    sales_conv = ConversationHandler(
        entry_points=[CommandHandler('add_sale', start_sale)],
        states={
            SALE_SEL_CUST: [CallbackQueryHandler(select_sale_customer, pattern='^sale_cust_\d+$')],
            SALE_SEL_STORE: [CallbackQueryHandler(select_sale_store, pattern='^sale_store_\d+$')],
            SALE_SEL_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_sale_item)],
            SALE_ASK_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_sale_quantity)],
            SALE_ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_sale_price)],
            SALE_ASK_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_sale_note)],
            SALE_CONFIRM: [CallbackQueryHandler(confirm_sale)]
        },
        fallbacks=[CommandHandler('cancel', cancel_sale)],
        allow_reentry=True
    )
    app.add_handler(sales_conv)

# --- Sales Flow Handlers ---
async def start_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Show customer list
    customers = secure_db.all('customers')
    buttons = [[InlineKeyboardButton(c['name'], callback_data=f'sale_cust_{c.doc_id}')] for c in customers]
    await update.message.reply_text('Select customer:', reply_markup=InlineKeyboardMarkup(buttons))
    return SALE_SEL_CUST

async def select_sale_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = int(update.callback_query.data.split('_')[-1])
    context.user_data['sale_customer_id'] = cid
    # Next: list stores
    stores = secure_db.all('stores')
    buttons = [[InlineKeyboardButton(s['name'], callback_data=f'sale_store_{s.doc_id}')] for s in stores]
    await update.callback_query.edit_message_text('Select store:', reply_markup=InlineKeyboardMarkup(buttons))
    return SALE_SEL_STORE

async def select_sale_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data['sale_store_id'] = sid
    await update.callback_query.edit_message_text('Enter item ID:')
    return SALE_SEL_ITEM

async def select_sale_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sale_item_id'] = int(update.message.text.strip())
    await update.message.reply_text('Enter quantity:')
    return SALE_ASK_QTY

async def ask_sale_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sale_qty'] = int(update.message.text.strip())
    await update.message.reply_text('Enter unit price:')
    return SALE_ASK_PRICE

async def ask_sale_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sale_price'] = float(update.message.text.strip())
    await update.message.reply_text('Optional note:')
    return SALE_ASK_NOTE

async def ask_sale_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sale_note'] = update.message.text.strip()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('✅ Confirm', callback_data='sale_confirm'),
        InlineKeyboardButton('❌ Cancel',  callback_data='sale_cancel'),
    ]])
    summary = (
        f"Item {context.user_data['sale_item_id']} x{context.user_data['sale_qty']} @"
        f"{context.user_data['sale_price']:.2f}"
    )
    await update.message.reply_text(summary, reply_markup=kb)
    return SALE_CONFIRM

async def confirm_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == 'sale_confirm':
        data = context.user_data
        secure_db.insert('customer_sales', {
            'customer_id': data['sale_customer_id'],
            'store_id': data['sale_store_id'],
            'item_id': data['sale_item_id'],
            'qty': data['sale_qty'],
            'unit_price': data['sale_price'],
            'note': data.get('sale_note',''),
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text('✅ Sale recorded.')
    else:
        await update.callback_query.edit_message_text('❌ Sale cancelled.')
    return ConversationHandler.END

async def cancel_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Sale entry cancelled.')
    return ConversationHandler.END
