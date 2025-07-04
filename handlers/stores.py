# handlers/stores.py

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

# State constants for Store CRUD flow
(
    S_NAME, S_CUR, S_CONFIRM,
    S_SEL_EDIT, S_NEW_NAME, S_NEW_CUR, S_CONFIRM_EDIT,
    S_SEL_REMOVE, S_CONFIRM_REMOVE, S_SEL_VIEW
) = range(10)

def register_store_handlers(app):
    store_conv = ConversationHandler(
        entry_points=[
            CommandHandler('add_store', add_store),
            CommandHandler('edit_store', edit_store),
            CommandHandler('remove_store', remove_store),
            CommandHandler('view_store', view_store),
        ],
        states={
            S_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_store_name)],
            S_CUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_store_currency)],
            S_CONFIRM: [CallbackQueryHandler(confirm_store)],
            S_SEL_EDIT: [CallbackQueryHandler(select_edit_store)],
            S_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_store_name)],
            S_NEW_CUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_store_currency)],
            S_CONFIRM_EDIT: [CallbackQueryHandler(confirm_edit_store)],
            S_SEL_REMOVE: [CallbackQueryHandler(select_remove_store)],
            S_CONFIRM_REMOVE: [CallbackQueryHandler(confirm_remove_store)],
            S_SEL_VIEW: [CallbackQueryHandler(view_store_details)],
        },
        fallbacks=[CommandHandler('cancel', cancel_store)],
        allow_reentry=True
    )
    app.add_handler(store_conv)

# --- Add Store ---
async def add_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter new store name:")
    return S_NAME

async def get_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['store_name'] = name
    await update.message.reply_text(f"Store name set to '{name}'. Now enter currency:")
    return S_CUR

async def get_store_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur = update.message.text.strip()
    context.user_data['store_currency'] = cur
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data='store_yes'),
        InlineKeyboardButton("❌ No",  callback_data='store_no')
    ]])
    await update.message.reply_text(
        f"Currency: {cur}\nSave this store?",
        reply_markup=kb
    )
    return S_CONFIRM

async def confirm_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == 'store_yes':
        secure_db.insert('stores', {
            'name': context.user_data['store_name'],
            'currency': context.user_data['store_currency'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            f"✅ Store '{context.user_data['store_name']}' added."
        )
    else:
        await update.callback_query.edit_message_text("❌ Add cancelled.")
    return ConversationHandler.END

# --- Edit Store (placeholder) ---
async def edit_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Edit feature not yet implemented.")
    return ConversationHandler.END

async def select_edit_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def new_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def new_store_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def confirm_edit_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

# --- Remove Store (placeholder) ---
async def remove_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Remove feature not yet implemented.")
    return ConversationHandler.END

async def select_remove_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

async def confirm_remove_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

# --- View Store (placeholder) ---
async def view_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("View feature not yet implemented.")
    return ConversationHandler.END

async def view_store_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

# --- Cancel Handler ---
async def cancel_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END