# handlers/customers.py

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

# Import the global secure_db instance from secure_db.py
from secure_db import secure_db

# State constants for Customer CRUD flow
(
    C_NAME, C_CUR, C_CONFIRM,
    C_SEL_EDIT, C_NEW_NAME, C_NEW_CUR, C_CONFIRM_EDIT,
    C_SEL_REMOVE, C_CONFIRM_REMOVE, C_SEL_VIEW
) = range(10)

def register_customer_handlers(app):
    customer_conv = ConversationHandler(
        entry_points=[
            CommandHandler('add_customer', add_customer),
            CommandHandler('edit_customer', edit_customer),
            CommandHandler('remove_customer', remove_customer),
            CommandHandler('view_customer', view_customer),
        ],
        states={
            C_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_name)],
            C_CUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_currency)],
            C_CONFIRM: [CallbackQueryHandler(confirm_customer)],
            C_SEL_EDIT: [CallbackQueryHandler(select_edit_customer)],
            C_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_customer_name)],
            C_NEW_CUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_customer_currency)],
            C_CONFIRM_EDIT: [CallbackQueryHandler(confirm_edit_customer)],
            C_SEL_REMOVE: [CallbackQueryHandler(select_remove_customer)],
            C_CONFIRM_REMOVE: [CallbackQueryHandler(confirm_remove_customer)],
            C_SEL_VIEW: [CallbackQueryHandler(view_customer_details)],
        },
        fallbacks=[CommandHandler('cancel', cancel_customer)],
        allow_reentry=True
    )
    app.add_handler(customer_conv)

# --- Add Customer ---
async def add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter new customer name:")
    return C_NAME

async def get_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['cust_name'] = name
    await update.message.reply_text(f"Name: {name}\nNow enter currency:")
    return C_CUR

async def get_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur = update.message.text.strip()
    context.user_data['cust_cur'] = cur
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data='cust_yes'),
        InlineKeyboardButton("❌ No",  callback_data='cust_no')
    ]])
    await update.message.reply_text(
        f"Currency: {cur}\nSave this customer?",
        reply_markup=kb
    )
    return C_CONFIRM

async def confirm_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == 'cust_yes':
        secure_db.insert('customers', {
            'name': context.user_data['cust_name'],
            'currency': context.user_data['cust_cur'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            f"✅ Customer {context.user_data['cust_name']} added."
        )
    else:
        await update.callback_query.edit_message_text("❌ Add cancelled.")
    return ConversationHandler.END

# --- Edit Customer (placeholders) ---
async def edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Edit feature not yet implemented.")
    return ConversationHandler.END

async def select_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def new_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def new_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def confirm_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

# --- Remove Customer ---
async def remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Remove feature not yet implemented.")
    return ConversationHandler.END

async def select_remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def confirm_remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

# --- View Customer ---
async def view_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("View feature not yet implemented.")
    return ConversationHandler.END

async def view_customer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

# --- Cancel Handler ---
async def cancel_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END