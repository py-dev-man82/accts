# handlers/customers.py

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

from handlers.utils import require_unlock
from secure_db import secure_db

# State constants for the customer flow
(C_NAME, C_CUR, C_CONFIRM) = range(3)

@require_unlock
async def add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Enter new customer name:")
    else:
        await update.message.reply_text("Enter new customer name:")
    return C_NAME

async def get_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['customer_name'] = name
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("USD", callback_data="cur_USD"),
         InlineKeyboardButton("EUR", callback_data="cur_EUR")]
    ])
    await update.message.reply_text(
        f"Name: {name}\nSelect currency:", reply_markup=kb
    )
    return C_CUR

async def get_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    currency = update.callback_query.data.split("_")[1]
    context.user_data['customer_currency'] = currency
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="cust_yes"),
         InlineKeyboardButton("❌ No",  callback_data="cust_no")]
    ])
    await update.callback_query.edit_message_text(
        f"Name: {context.user_data['customer_name']}\n"
        f"Currency: {currency}\nSave?",
        reply_markup=kb
    )
    return C_CONFIRM

@require_unlock
async def confirm_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'cust_yes':
        secure_db.insert('customers', {
            'name': context.user_data['customer_name'],
            'currency': context.user_data['customer_currency'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            f"✅ Customer '{context.user_data['customer_name']}' added."
        )
    else:
        await update.callback_query.edit_message_text("❌ Add cancelled.")
    return ConversationHandler.END

def register_customer_handlers(app):
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_customer", add_customer),
            CallbackQueryHandler(add_customer, pattern="^add_customer$")
        ],
        states={
            C_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_name)],
            C_CUR:     [CallbackQueryHandler(get_customer_currency, pattern="^cur_")],
            C_CONFIRM: [CallbackQueryHandler(confirm_customer, pattern="^cust_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_customer)],
        per_message=False
    )
    app.add_handler(conv)