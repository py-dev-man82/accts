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
from secure_db import secure_db

# State constants for Customer CRUD flow
(
    C_NAME, C_CUR, C_CONFIRM,
    C_SEL_EDIT, C_NEW_NAME, C_NEW_CUR, C_CONFIRM_EDIT,
    C_SEL_REMOVE, C_CONFIRM_REMOVE, C_SEL_VIEW
) = range(10)

# Register Customer Handlers
def register_customer_handlers(app):
    customer_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('add_customer', add_customer),
            CommandHandler('edit_customer', edit_customer),
            CommandHandler('remove_customer', remove_customer),
            CommandHandler('view_customer', view_customer),
        ],
        states={
            C_NAME: [MessageHandler(filters.text, get_customer_name)],
            C_CUR: [MessageHandler(filters.text, get_customer_currency)],
            C_CONFIRM: [CallbackQueryHandler(confirm_customer)],
            C_SEL_EDIT: [CallbackQueryHandler(select_edit_customer)],
            C_NEW_NAME: [MessageHandler(filters.text, new_customer_name)],
            C_NEW_CUR: [MessageHandler(filters.text, new_customer_currency)],
            C_CONFIRM_EDIT: [CallbackQueryHandler(confirm_edit_customer)],
            C_SEL_REMOVE: [CallbackQueryHandler(select_remove_customer)],
            C_CONFIRM_REMOVE: [CallbackQueryHandler(confirm_remove_customer)],
            C_SEL_VIEW: [CallbackQueryHandler(view_customer_details)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_customer)
        ]
    )
    
    app.add_handler(customer_conv_handler)

# Handlers for different customer CRUD operations
async def add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please enter the customer name.")
    return C_NAME

async def get_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer_name = update.message.text
    context.user_data['customer_name'] = customer_name
    await update.message.reply_text(f"Customer name is {customer_name}. Now, enter the currency.")
    return C_CUR

async def get_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer_currency = update.message.text
    context.user_data['customer_currency'] = customer_currency
    await update.message.reply_text(f"Currency is {customer_currency}. Confirm to save?")
    return C_CONFIRM

async def confirm_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer_name = context.user_data.get('customer_name')
    customer_currency = context.user_data.get('customer_currency')
    secure_db.insert('customers', {'name': customer_name, 'currency': customer_currency})
    await update.message.reply_text(f"Customer {customer_name} with currency {customer_currency} added.")
    return ConversationHandler.END

async def edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder for the edit logic
    await update.message.reply_text("Enter the name of the customer to edit.")
    return C_SEL_EDIT

async def select_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle customer selection for editing
    await update.message.reply_text("Select a field to edit.")
    return C_NEW_NAME

async def new_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text
    context.user_data['new_name'] = new_name
    await update.message.reply_text(f"New name is {new_name}. Now enter the new currency.")
    return C_NEW_CUR

async def new_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_currency = update.message.text
    context.user_data['new_currency'] = new_currency
    await update.message.reply_text(f"New currency is {new_currency}. Confirm to update?")
    return C_CONFIRM_EDIT

async def confirm_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Confirm customer update
    new_name = context.user_data.get('new_name')
    new_currency = context.user_data.get('new_currency')
    # Logic to update customer in database
    await update.message.reply_text(f"Customer updated to {new_name} with currency {new_currency}.")
    return ConversationHandler.END

async def remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter the name of the customer to remove.")
    return C_SEL_REMOVE

async def select_remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle customer removal selection
    await update.message.reply_text("Are you sure you want to remove this customer?")
    return C_CONFIRM_REMOVE

async def confirm_remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Logic to remove customer from database
    await update.message.reply_text("Customer removed.")
    return ConversationHandler.END

async def view_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Select the customer to view.")
    return C_SEL_VIEW

async def view_customer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Display customer details
    await update.message.reply_text("Displaying customer details.")
    return ConversationHandler.END

async def cancel_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Customer action cancelled.")
    return ConversationHandler.END