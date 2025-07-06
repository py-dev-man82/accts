# handlers/partners.py

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
    P_VIEW,
    P_EDIT_SELECT,
    P_EDIT_NAME,
    P_EDIT_CUR,
    P_EDIT_CONFIRM,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM
) = range(10)

# --- Submenu for Partner Management ---
async def show_partner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Partner Management: choose an action",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Partner",     callback_data="add_partner")],
                [InlineKeyboardButton("👀 View Partners",   callback_data="view_partner")],
                [InlineKeyboardButton("✏️ Edit Partner",   callback_data="edit_partner")],
                [InlineKeyboardButton("🗑️ Remove Partner", callback_data="remove_partner")],
                [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
            ])
        )
    return

# --- Add Partner Flow ---
@require_unlock
async def add_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Enter new partner name:")
    else:
        await update.message.reply_text("Enter new partner name:")
    return P_NAME

async def get_partner_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['partner_name'] = name
    await update.message.reply_text("Enter currency for this partner:")
    return P_CUR

async def get_partner_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur = update.message.text.strip()
    context.user_data['partner_currency'] = cur
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="partner_yes"),
         InlineKeyboardButton("❌ No",  callback_data="partner_no")]
    ])
    await update.callback_query.edit_message_text(
        f"Name: {context.user_data['partner_name']}\n"
        f"Currency: {cur}\nSave?", reply_markup=kb
    )
    return P_CONFIRM

@require_unlock
async def confirm_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'partner_yes':
        secure_db.insert('partners', {
            'name': context.user_data['partner_name'],
            'currency': context.user_data['partner_currency'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            f"✅ Partner '{context.user_data['partner_name']}' added."
        )
    else:
        await update.callback_query.edit_message_text("❌ Add cancelled.")
    return ConversationHandler.END

# --- View Partner Flow ---
@require_unlock
async def view_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    records = secure_db.all('partners')
    if not records:
        await update.callback_query.edit_message_text("No partners found.")
        return ConversationHandler.END
    text = "📋 Partners List:\n"
    for rec in records:
        text += f"• {rec.doc_id}: {rec['name']} ({rec['currency']})\n"
    await update.callback_query.edit_message_text(text)
    return ConversationHandler.END

# --- Edit Partner Flow ---
@require_unlock
async def edit_partner_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    records = secure_db.all('partners')
    if not records:
        await update.callback_query.edit_message_text("No partners to edit.")
        return ConversationHandler.END
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{r.doc_id}: {r['name']}", callback_data=f"edit_partner_{r.doc_id}")] for r in records
    ])
    await update.callback_query.edit_message_text("Select partner to edit:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = update.callback_query.data
    try:
        pid = int(data.rsplit("_", 1)[1])
    except:
        await update.callback_query.edit_message_text("Invalid selection.")
        return ConversationHandler.END
    q = Query()
    res = secure_db.search('partners', q.doc_id == pid)
    if not res:
        await update.callback_query.edit_message_text("Partner not found.")
        return ConversationHandler.END
    rec = res[0]
    context.user_data['edit_partner'] = rec
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Change Name", callback_data="pedit_name")],
        [InlineKeyboardButton("✅ Change Currency", callback_data="pedit_cur")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="partner_conf_no")]
    ])
    await update.callback_query.edit_message_text(
        f"Editing: {rec['name']} ({rec['currency']})\nChoose field:", reply_markup=kb
    )
    return P_EDIT_NAME

async def get_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Enter new name:")
    return P_EDIT_CUR

async def get_edit_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['new_partner_currency'] = text
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="partner_update_yes"),
         InlineKeyboardButton("❌ No",  callback_data="partner_update_no")]
    ])
    await update.message.reply_text(
        f"Change to currency: {text}?", reply_markup=kb
    )
    return P_EDIT_CONFIRM

@require_unlock
async def confirm_edit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'partner_update_yes':
        rec = context.user_data['edit_partner']
        secure_db.update('partners', {
            'name': context.user_data.get('new_partner_name', rec['name']),
            'currency': context.user_data.get('new_partner_currency', rec['currency'])
        }, [rec.doc_id])
        await update.callback_query.edit_message_text("✅ Partner updated.")
    else:
        await update.callback_query.edit_message_text("❌ Edit cancelled.")
    return ConversationHandler.END

# --- Delete Partner Flow ---
@require_unlock
async def remove_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    records = secure_db.all('partners')
    if not records:
        await update.callback_query.edit_message_text("No partners to remove.")
        return ConversationHandler.END
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{r.doc_id}: {r['name']}", callback_data=f"delete_partner_{r.doc_id}")] for r in records
    ])
    await update.callback_query.edit_message_text("Select partner to remove:", reply_markup=kb)
    return P_DELETE_SELECT

async def get_delete_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    try:
        pid = int(update.callback_query.data.rsplit("_", 1)[1])
    except:
        await update.callback_query.edit_message_text("Invalid selection.")
        return ConversationHandler.END
    context.user_data['delete_partner_id'] = pid
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="partner_del_yes"),
         InlineKeyboardButton("❌ No",  callback_data="partner_del_no")]
    ])
    await update.callback_query.edit_message_text(
        f"Are you sure you want to delete partner ID {pid}?", reply_markup=kb
    )
    return P_DELETE_CONFIRM

@require_unlock
async def confirm_delete_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'partner_del_yes':
        pid = context.user_data['delete_partner_id']
        secure_db.remove('partners', [pid])
        await update.callback_query.edit_message_text("✅ Partner removed.")
    else:
        await update.callback_query.edit_message_text("❌ Delete cancelled.")
    return ConversationHandler.END


def register_partner_handlers(app):
    # Show submenu
    app.add_handler(CallbackQueryHandler(show_partner_menu, pattern="^partner_menu$"))

    # Add flow
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_partner", add_partner),
            CallbackQueryHandler(add_partner, pattern="^add_partner$")
        ],
        states={
            P_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_name)],
            P_CUR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_currency)],
            P_CONFIRM:[CallbackQueryHandler(confirm_partner, pattern="^partner_(yes|no)$")]
        },
        fallbacks=[CommandHandler("cancel", confirm_partner)],
        per_message=False
    )
    app.add_handler(add_conv)

    # View flow
    view_conv = ConversationHandler(
        entry_points=[
            CommandHandler("view_partner", view_partner),
            CallbackQueryHandler(view_partner, pattern="^view_partner$")
        ],
        states={},
        fallbacks=[],
        per_message=False
    )
    app.add_handler(view_conv)

    # Edit flow
    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_partner", edit_partner_start),
            CallbackQueryHandler(edit_partner_start, pattern="^edit_partner$")
        ],
        states={
            P_EDIT_SELECT: [CallbackQueryHandler(get_edit_selection, pattern="^edit_partner_\d+$")],
            P_EDIT_NAME:   [CallbackQueryHandler(get_edit_name, pattern="^pedit_name$")],
            P_EDIT_CUR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_currency)],
            P_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_partner, pattern="^partner_update_(yes|no)$")]
        },
        fallbacks=[CommandHandler("cancel", confirm_edit_partner)],
        per_message=False
    )
    app.add_handler(edit_conv)

    # Delete flow
    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("remove_partner", remove_partner),
            CallbackQueryHandler(remove_partner, pattern="^remove_partner$")
        ],
        states={
            P_DELETE_SELECT: [CallbackQueryHandler(get_delete_selection, pattern="^delete_partner_\d+$")],
            P_DELETE_CONFIRM:[CallbackQueryHandler(confirm_delete_partner, pattern="^partner_del_(yes|no)$")]
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_partner)],
        per_message=False
    )
    app.add_handler(del_conv)
