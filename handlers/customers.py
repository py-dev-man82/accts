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
    # Entry point via /add_customer or button
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Enter new customer name:")
    else:
        await update.message.reply_text("Enter new customer name:")
    return C_NAME

async def get_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['customer_name'] = name
    # Ask user to input currency code free-text
    await update.message.reply_text(
        f"Name: {name}\nEnter currency code (e.g. USD, EUR) or type 'list' to see options:")
    return C_CUR

async def get_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    # Optionally validate or show list
    if currency == 'LIST':
        await update.message.reply_text("Supported currencies: USD, EUR, GBP, JPY, AUD, CAD, CHF, CNY, SEK, NZD")
        return C_CUR
    context.user_data['customer_currency'] = currency
    # Confirm details
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="cust_yes"),
         InlineKeyboardButton("❌ No",  callback_data="cust_no")]
    ])
    await update.message.reply_text(
        f"Name: {context.user_data['customer_name']}\n"
        f"Currency: {currency}\nSave?", reply_markup=kb
    )
    return C_CONFIRM

@require_unlock
async def confirm_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle yes/no confirmation
    if update.callback_query:
        await update.callback_query.answer()
        choice = update.callback_query.data
    else:
        choice = update.message.text.strip().lower()
    if choice == 'cust_yes' or choice == 'yes':
        secure_db.insert('customers', {
            'name': context.user_data['customer_name'],
            'currency': context.user_data['customer_currency'],
            'created_at': datetime.utcnow().isoformat()
        })
        text = f"✅ Customer '{context.user_data['customer_name']}' added."
    else:
        text = "❌ Add cancelled."
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)
    return ConversationHandler.END

async def cancel_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


def register_customer_handlers(app):
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_customer", add_customer),
            CallbackQueryHandler(add_customer, pattern="^add_customer$"),
        ],
        states={
            C_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_name)],
            C_CUR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_currency)],
            C_CONFIRM: [CallbackQueryHandler(confirm_customer, pattern="^cust_"),
                        MessageHandler(filters.Regex('^(yes|no|✅ Yes|❌ No)$'), confirm_customer)],
        },
        fallbacks=[CommandHandler("cancel", cancel_customer)],
        per_message=False
    )
    app.add_handler(conv)
