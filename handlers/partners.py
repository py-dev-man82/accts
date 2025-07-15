# handlers/partners.py 

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

# State constants for the partner flow
(
    P_NAME,
    P_CUR,
    P_CONFIRM,
    P_EDIT_SELECT,
    P_EDIT_NAME,
    P_EDIT_CUR,
    P_EDIT_CONFIRM,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM,
) = range(9)

# --- Submenu for Partner Management ---
async def show_partner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing partner submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Partner",    callback_data="add_partner")],
            [InlineKeyboardButton("👀 View Partners", callback_data="view_partner")],
            [InlineKeyboardButton("✏️ Edit Partner",  callback_data="edit_partner")],
            [InlineKeyboardButton("🗑️ Remove Partner",callback_data="remove_partner")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])
        await update.callback_query.edit_message_text(
            "Partner Management: choose an action",
            reply_markup=kb
        )

# --- Add Partner Flow ---
@require_unlock
async def add_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_partner")
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Enter new partner name:")
    else:
        await update.message.reply_text("Enter new partner name:")
    return P_NAME

async def get_partner_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received partner name: %s", update.message.text)
    context.user_data['partner_name'] = update.message.text.strip()
    await update.message.reply_text("Enter currency code for this partner (e.g. USD):")
    return P_CUR

async def get_partner_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received partner currency: %s", update.message.text)
    context.user_data['partner_currency'] = update.message.text.strip().upper()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="partner_yes"),
         InlineKeyboardButton("❌ No",  callback_data="partner_no")]
    ])
    await update.message.reply_text(
        f"Name: {context.user_data['partner_name']}\n"
        f"Currency: {context.user_data['partner_currency']}\nSave?",
        reply_markup=kb
    )
    return P_CONFIRM

@require_unlock
async def confirm_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Confirm add_partner: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'partner_yes':
        secure_db.insert('partners', {
            'name':       context.user_data['partner_name'],
            'currency':   context.user_data['partner_currency'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            f"✅ Partner '{context.user_data['partner_name']}' added.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_menu")]])
        )
    else:
        await show_partner_menu(update, context)
    return ConversationHandler.END

# --- View Partners Flow ---
async def view_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View partners")
    await update.callback_query.answer()
    rows = secure_db.all('partners')
    if not rows:
        text = "No partners found."
    else:
        lines = [f"• [{r.doc_id}] {r['name']} ({r['currency']})" for r in rows]
        text = "Partners:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# --- Edit Partner Flow ---
@require_unlock
async def edit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start edit_partner")
    await update.callback_query.answer()
    rows = secure_db.all('partners')
    if not rows:
        await update.callback_query.edit_message_text(
            "No partners to edit.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"edit_partner_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a partner to edit:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_partner_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_partner_edit_selection: %s", update.callback_query.data)
    await update.callback_query.answer()
    parts = update.callback_query.data.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await show_partner_menu(update, context)
    pid = int(parts[1])
    rec = secure_db.table('partners').get(doc_id=pid)
    if not rec:
        return await show_partner_menu(update, context)
    context.user_data['edit_partner'] = rec
    await update.callback_query.edit_message_text("Enter the new partner name:")
    return P_EDIT_NAME

async def get_edit_partner_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_edit_partner_name: %s", update.message.text)
    context.user_data['new_partner_name'] = update.message.text.strip()
    await update.message.reply_text("Enter the new currency code:")
    return P_EDIT_CUR

async def get_edit_partner_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_edit_partner_currency: %s", update.message.text)
    context.user_data['new_partner_cur'] = update.message.text.strip().upper()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Save", callback_data="partner_conf_yes"),
        InlineKeyboardButton("❌ Cancel", callback_data="partner_conf_no")
    ]])
    await update.message.reply_text(
        f"Save changes for '{context.user_data['edit_partner']['name']}'?",
        reply_markup=kb
    )
    return P_EDIT_CONFIRM

@require_unlock
async def confirm_edit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_edit_partner: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'partner_conf_yes':
        rec = context.user_data['edit_partner']
        secure_db.update('partners', {
            'name':     context.user_data['new_partner_name'],
            'currency': context.user_data['new_partner_cur']
        }, [rec.doc_id])
        await update.callback_query.edit_message_text(
            f"✅ Updated to {context.user_data['new_partner_name']} ({context.user_data['new_partner_cur']}).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_menu")]])
        )
    else:
        await show_partner_menu(update, context)
    return ConversationHandler.END

# --- Delete Partner Flow ---
@require_unlock
async def delete_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start delete_partner")
    await update.callback_query.answer()
    rows = secure_db.all('partners')
    if not rows:
        await update.callback_query.edit_message_text(
            "No partners to remove.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"delete_partner_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a partner to delete:", reply_markup=kb)
    return P_DELETE_SELECT

async def get_delete_partner_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_delete_partner_selection: %s", update.callback_query.data)
    await update.callback_query.answer()
    parts = update.callback_query.data.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await show_partner_menu(update, context)
    pid = int(parts[1])
    rec = secure_db.table('partners').get(doc_id=pid)
    if not rec:
        return await show_partner_menu(update, context)
    context.user_data['del_partner'] = rec
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, delete", callback_data="partner_del_yes"),
        InlineKeyboardButton("❌ No, cancel",  callback_data="partner_del_no")
    ]])
    await update.callback_query.edit_message_text(
        f"Are you sure you want to delete {rec['name']}?",
        reply_markup=kb
    )
    return P_DELETE_CONFIRM

@require_unlock
async def confirm_delete_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_delete_partner: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'partner_del_yes':
        rec = context.user_data['del_partner']
        secure_db.remove('partners', [rec.doc_id])
        await update.callback_query.edit_message_text(
            f"✅ Partner '{rec['name']}' deleted.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_menu")]])
        )
    else:
        await show_partner_menu(update, context)
    return ConversationHandler.END

# --- Register Handlers ---
def register_partner_handlers(app):
    app.add_handler(CallbackQueryHandler(show_partner_menu, pattern="^partner_menu$"))

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_partner", add_partner),
            CallbackQueryHandler(add_partner, pattern="^add_partner$")
        ],
        states={
            P_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_name)],
            P_CUR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_currency)],
            P_CONFIRM: [CallbackQueryHandler(confirm_partner, pattern="^partner_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_partner)],
        per_message=False
    )
    app.add_handler(add_conv)

    app.add_handler(CallbackQueryHandler(view_partner, pattern="^view_partner$"))

    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_partner", edit_partner),
            CallbackQueryHandler(edit_partner, pattern="^edit_partner$")
        ],
        states={
            P_EDIT_SELECT: [CallbackQueryHandler(get_partner_edit_selection, pattern="^edit_partner_")],
            P_EDIT_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_partner_name)],
            P_EDIT_CUR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_partner_currency)],
            P_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_partner, pattern="^partner_conf_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_edit_partner)],
        per_message=False
    )
    app.add_handler(edit_conv)

    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("remove_partner", delete_partner),
            CallbackQueryHandler(delete_partner, pattern="^remove_partner$")
        ],
        states={
            P_DELETE_SELECT: [CallbackQueryHandler(get_delete_partner_selection, pattern="^delete_partner_")],
            P_DELETE_CONFIRM:[CallbackQueryHandler(confirm_delete_partner, pattern="^partner_del_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_partner)],
        per_message=False
    )
    app.add_handler(del_conv)
