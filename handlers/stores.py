# handlers/stores.py

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

# State constants for the store flow
(S_NAME, S_CUR, S_CONFIRM) = range(3)

# --- Submenu for Store Management ---
async def show_store_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Store Management: choose an action",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Store",     callback_data="add_store")],
                [InlineKeyboardButton("👀 View Stores",   callback_data="view_store")],
                [InlineKeyboardButton("✏️ Edit Store",  callback_data="edit_store")],
                [InlineKeyboardButton("🗑️ Remove Store",callback_data="remove_store")],
                [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
            ])
        )
    return

@require_unlock
async def add_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Enter new store name:")
    else:
        await update.message.reply_text("Enter new store name:")
    return S_NAME

async def get_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['store_name'] = name
    await update.message.reply_text("Enter currency for this store:")
    return S_CUR

async def get_store_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip()
    context.user_data['store_currency'] = currency
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="store_yes"),
         InlineKeyboardButton("❌ No",  callback_data="store_no")]
    ])
    await update.message.reply_text(
        f"Name: {context.user_data['store_name']}\n"
        f"Currency: {currency}\nSave?",
        reply_markup=kb
    )
    return S_CONFIRM

@require_unlock
async def confirm_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
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


def register_store_handlers(app):
    # Submenu
    app.add_handler(CallbackQueryHandler(show_store_menu, pattern="^store_menu$"))

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_store", add_store),
            CallbackQueryHandler(add_store, pattern="^add_store$")
        ],
        states={
            S_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_store_name)],
            S_CUR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_store_currency)],
            S_CONFIRM: [CallbackQueryHandler(confirm_store, pattern="^store_(yes|no)$")]
        },
        fallbacks=[CommandHandler("cancel", confirm_store)],
        per_message=False
    )
    app.add_handler(conv)
