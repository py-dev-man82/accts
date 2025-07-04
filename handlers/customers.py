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
from bot import secure_db   # use the instance from bot.py

# State constants for Customer CRUD flow
(
    C_NAME, C_CUR, C_CONFIRM,
    C_SEL_EDIT, C_NEW_NAME, C_NEW_CUR, C_CONFIRM_EDIT,
    C_SEL_REMOVE, C_CONFIRM_REMOVE, C_SEL_VIEW
) = range(10)

def register_customer_handlers(app):
    customer_conv_handler = ConversationHandler(
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
    app.add_handler(customer_conv_handler)

async def add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please enter the customer name.")
    return C_NAME

async def get_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer_name = update.message.text.strip()
    context.user_data['customer_name'] = customer_name
    await update.message.reply_text(f"Customer name is '{customer_name}'. Now enter the currency.")
    return C_CUR

async def get_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customer_currency = update.message.text.strip()
    context.user_data['customer_currency'] = customer_currency
    buttons = [
        InlineKeyboardButton("✅ Yes", callback_data='confirm_cust'),
        InlineKeyboardButton("❌ No",  callback_data='cancel_cust')
    ]
    await update.message.reply_text(
        f"Currency set to '{customer_currency}'. Confirm to save?",
        reply_markup=InlineKeyboardMarkup([buttons])
    )
    return C_CONFIRM

async def confirm_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == 'confirm_cust':
        name = context.user_data['customer_name']
        cur  = context.user_data['customer_currency']
        secure_db.insert('customers', {
            'name': name,
            'currency': cur,
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(f"✅ Added customer '{name}' ({cur}).")
    else:
        await update.callback_query.edit_message_text("❌ Cancelled.")
    return ConversationHandler.END

async def edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder: list customers to select for editing
    await update.message.reply_text("Enter the name of the customer to edit.")
    return C_SEL_EDIT

async def select_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder for selecting and editing
    await update.callback_query.edit_message_text("Feature coming soon.")
    return ConversationHandler.END

async def new_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder
    return ConversationHandler.END

async def new_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder
    return ConversationHandler.END

async def confirm_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder
    return ConversationHandler.END

async def remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter the name of the customer to remove.")
    return C_SEL_REMOVE

async def select_remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder
    await update.callback_query.edit_message_text("Are you sure you want to remove this customer?")
    return C_CONFIRM_REMOVE

async def confirm_remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == 'confirm_remove':
        # Placeholder for deletion logic
        await update.callback_query.edit_message_text("✅ Customer removed.")
    else:
        await update.callback_query.edit_message_text("❌ Cancelled.")
    return ConversationHandler.END

async def view_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder: show list of customers
    await update.message.reply_text("Select a customer to view.")
    return C_SEL_VIEW

async def view_customer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Placeholder for details display
    await update.callback_query.edit_message_text("Customer details here.")
    return ConversationHandler.END

async def cancel_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END