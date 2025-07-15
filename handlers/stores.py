# handlers/stores.py 

import logging
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
(
    S_NAME,
    S_CUR,
    S_CONFIRM,
    S_EDIT_SELECT,
    S_EDIT_NAME,
    S_EDIT_CUR,
    S_EDIT_CONFIRM,
    S_DELETE_SELECT,
    S_DELETE_CONFIRM,
) = range(9)

# --- Submenu for Store Management ---
async def show_store_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing store submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Store",    callback_data="add_store")],
            [InlineKeyboardButton("👀 View Stores", callback_data="view_store")],
            [InlineKeyboardButton("✏️ Edit Store",  callback_data="edit_store")],
            [InlineKeyboardButton("🗑️ Remove Store",callback_data="remove_store")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])
        await update.callback_query.edit_message_text(
            "Store Management: choose an action",
            reply_markup=kb
        )

# --- Add Store Flow ---
@require_unlock
async def add_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_store")
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Enter new store name:")
    else:
        await update.message.reply_text("Enter new store name:")
    return S_NAME

async def get_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received store name: %s", update.message.text)
    context.user_data['store_name'] = update.message.text.strip()
    await update.message.reply_text("Enter currency code for this store (e.g. USD):")
    return S_CUR

async def get_store_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received store currency: %s", update.message.text)
    context.user_data['store_currency'] = update.message.text.strip().upper()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="store_yes"),
         InlineKeyboardButton("❌ No",  callback_data="store_no")]
    ])
    await update.message.reply_text(
        f"Name: {context.user_data['store_name']}\n"
        f"Currency: {context.user_data['store_currency']}\nSave?",
        reply_markup=kb
    )
    return S_CONFIRM

@require_unlock
async def confirm_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Confirm add_store: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'store_yes':
        secure_db.insert('stores', {
            'name':       context.user_data['store_name'],
            'currency':   context.user_data['store_currency'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            f"✅ Store '{context.user_data['store_name']}' added.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="store_menu")]])
        )
    else:
        await show_store_menu(update, context)
    return ConversationHandler.END

# --- View Stores Flow ---
async def view_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View stores")
    await update.callback_query.answer()
    rows = secure_db.all('stores')
    if not rows:
        text = "No stores found."
    else:
        lines = [f"• [{r.doc_id}] {r['name']} ({r['currency']})" for r in rows]
        text = "Stores:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="store_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# --- Edit Store Flow ---
@require_unlock
async def edit_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start edit_store")
    await update.callback_query.answer()
    rows = secure_db.all('stores')
    if not rows:
        await update.callback_query.edit_message_text(
            "No stores to edit.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="store_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"edit_store_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a store to edit:", reply_markup=kb)
    return S_EDIT_SELECT

async def get_store_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_store_edit_selection: %s", update.callback_query.data)
    await update.callback_query.answer()
    parts = update.callback_query.data.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await show_store_menu(update, context)
    sid = int(parts[1])
    rec = secure_db.table('stores').get(doc_id=sid)
    if not rec:
        return await show_store_menu(update, context)
    context.user_data['edit_store'] = rec
    await update.callback_query.edit_message_text("Enter the new store name:")
    return S_EDIT_NAME

async def get_store_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_store_new_name: %s", update.message.text)
    context.user_data['new_store_name'] = update.message.text.strip()
    await update.message.reply_text("Enter the new currency code:")
    return S_EDIT_CUR

async def get_store_new_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_store_new_currency: %s", update.message.text)
    context.user_data['new_store_cur'] = update.message.text.strip().upper()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Save", callback_data="store_conf_yes"),
        InlineKeyboardButton("❌ Cancel", callback_data="store_conf_no")
    ]])
    await update.message.reply_text(
        f"Save changes for '{context.user_data['edit_store']['name']}'?",
        reply_markup=kb
    )
    return S_EDIT_CONFIRM

@require_unlock
async def confirm_edit_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_edit_store: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'store_conf_yes':
        rec = context.user_data['edit_store']
        secure_db.update('stores', {
            'name':     context.user_data['new_store_name'],
            'currency': context.user_data['new_store_cur']
        }, [rec.doc_id])
        await update.callback_query.edit_message_text(
            f"✅ Updated to {context.user_data['new_store_name']} ({context.user_data['new_store_cur']}).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="store_menu")]])
        )
    else:
        await show_store_menu(update, context)
    return ConversationHandler.END

# --- Delete Store Flow ---
@require_unlock
async def delete_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start delete_store")
    await update.callback_query.answer()
    rows = secure_db.all('stores')
    if not rows:
        await update.callback_query.edit_message_text(
            "No stores to remove.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="store_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"delete_store_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a store to delete:", reply_markup=kb)
    return S_DELETE_SELECT

async def get_delete_store_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_delete_store_selection: %s", update.callback_query.data)
    await update.callback_query.answer()
    parts = update.callback_query.data.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await show_store_menu(update, context)
    sid = int(parts[1])
    rec = secure_db.table('stores').get(doc_id=sid)
    if not rec:
        return await show_store_menu(update, context)
    context.user_data['del_store'] = rec
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, delete", callback_data="store_del_yes"),
        InlineKeyboardButton("❌ No, cancel",  callback_data="store_del_no")
    ]])
    await update.callback_query.edit_message_text(
        f"Are you sure you want to delete {rec['name']}", reply_markup=kb
    )
    return S_DELETE_CONFIRM

@require_unlock
async def confirm_delete_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_delete_store: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'store_del_yes':
        rec = context.user_data['del_store']
        secure_db.remove('stores', [rec.doc_id])
        await update.callback_query.edit_message_text(
            f"✅ Store '{rec['name']}' deleted.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="store_menu")]])
        )
    else:
        await show_store_menu(update, context)
    return ConversationHandler.END

# --- Register Handlers ---
def register_store_handlers(app):
    app.add_handler(CallbackQueryHandler(show_store_menu, pattern="^store_menu$"))

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_store", add_store),
            CallbackQueryHandler(add_store, pattern="^add_store$")
        ],
        states={
            S_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_store_name)],
            S_CUR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_store_currency)],
            S_CONFIRM: [CallbackQueryHandler(confirm_store, pattern="^store_")]  
        },
        fallbacks=[CommandHandler("cancel", confirm_store)],
        per_message=False
    )
    app.add_handler(add_conv)

    app.add_handler(CallbackQueryHandler(view_store, pattern="^view_store$"))

    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_store", edit_store),
            CallbackQueryHandler(edit_store, pattern="^edit_store$")
        ],
        states={
            S_EDIT_SELECT: [CallbackQueryHandler(get_store_edit_selection, pattern="^edit_store_")],
            S_EDIT_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_store_new_name)],
            S_EDIT_CUR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_store_new_currency)],
            S_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_store, pattern="^store_conf_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_edit_store)],
        per_message=False
    )
    app.add_handler(edit_conv)

    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("remove_store", delete_store),
            CallbackQueryHandler(delete_store, pattern="^remove_store$")
        ],
        states={
            S_DELETE_SELECT: [CallbackQueryHandler(get_delete_store_selection, pattern="^delete_store_")],
            S_DELETE_CONFIRM:[CallbackQueryHandler(confirm_delete_store, pattern="^store_del_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_store)],
        per_message=False
    )
    app.add_handler(del_conv)
