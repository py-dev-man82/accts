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
from bot import require_unlock
from secure_db import secure_db

# State constants for the customer flow
(
    C_NAME,
    C_CUR,
    C_CONFIRM
) = range(3)

# Entry point: starts when /add_customer or corresponding button pressed
@require_unlock
async def add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Acknowledge callback if from button
    if update.callback_query:
        await update.callback_query.answer()
    await update.message.reply_text(
        "Enter new customer name:"
    )
    return C_NAME

# Collect customer name
async def get_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['customer_name'] = update.message.text.strip()
    await update.message.reply_text(
        f"Name: {context.user_data['customer_name']}\nEnter currency code (e.g. USD):"
    )
    return C_CUR

# Collect currency
async def get_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['customer_currency'] = update.message.text.strip().upper()
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes", callback_data="customer_yes"),
            InlineKeyboardButton("❌ No", callback_data="customer_no")
        ]
    ])
    await update.message.reply_text(
        f"Customer: {context.user_data['customer_name']} ({context.user_data['customer_currency']})\nSave this customer?",
        reply_markup=kb
    )
    return C_CONFIRM

# Confirmation callback
@require_unlock
async def confirm_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'customer_yes':
        secure_db.insert('customers', {
            'name': context.user_data['customer_name'],
            'currency': context.user_data['customer_currency'],
            'created_at': datetime.utcnow().isoformat()
        })
        await query.edit_message_text(
            f"✅ Customer '{context.user_data['customer_name']}' added."
        )
    else:
        await query.edit_message_text("❌ Add customer cancelled.")
    return ConversationHandler.END

# Fallback/cancel handler
async def cancel_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# Register this conversation flow on the Application
def register_customer_handlers(app):
    customer_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_customer", add_customer),
            CallbackQueryHandler(add_customer, pattern="^add_customer$")
        ],
        states={
            C_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_name)],
            C_CUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_currency)],
            C_CONFIRM: [CallbackQueryHandler(confirm_customer, pattern="^customer_(yes|no)$")]
        },
        fallbacks=[CommandHandler("cancel", cancel_customer)],
        per_message=False
    )
    app.add_handler(customer_conv)
