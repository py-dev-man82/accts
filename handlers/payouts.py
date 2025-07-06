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

# State constants for the payout flow
(
    P_PARTNER_SELECT,
    P_LOCAL_AMT,
    P_USD_PAID,
    P_NOTE,
    P_CONFIRM,
    P_EDIT_PARTNER,
    P_EDIT_SELECT,
    P_EDIT_LOCAL,
    P_EDIT_USD,
    P_EDIT_NOTE,
    P_EDIT_CONFIRM,
    P_DELETE_PARTNER,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM,
) = range(14)

# --- Submenu for Payouts ---
async def show_payout_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payout submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Payout", callback_data="add_payout")],
            [InlineKeyboardButton("👀 View Payouts", callback_data="view_payout")],
            [InlineKeyboardButton("✏️ Edit Payout", callback_data="edit_payout")],
            [InlineKeyboardButton("🗑️ Remove Payout", callback_data="remove_payout")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])
        await update.callback_query.edit_message_text(
            "Payouts: choose an action", reply_markup=kb
        )

# --- Add Payout Flow ---
@require_unlock
async def add_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_payout")
    await update.callback_query.answer()
    partners = secure_db.all('partners')
    buttons = [InlineKeyboardButton(f"{p['name']}", callback_data=f"pout_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a partner:", reply_markup=kb)
    return P_PARTNER_SELECT

async def get_payout_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data['partner_id'] = pid
    await update.callback_query.edit_message_text("Enter local amount to pay:")
    return P_LOCAL_AMT

async def get_payout_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amt = float(update.message.text)
    context.user_data['local_amt'] = amt
    await update.message.reply_text("Enter USD paid:")
    return P_USD_PAID

async def get_payout_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usd = float(update.message.text)
    context.user_data['usd_amt'] = usd
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 Add Note", callback_data="note_yes"),
        InlineKeyboardButton("⏭️ Skip Note", callback_data="note_skip"),
    ]])
    await update.message.reply_text("Optional: add a note?", reply_markup=kb)
    return P_NOTE

async def get_payout_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    choice = update.callback_query.data
    if choice == 'note_skip':
        context.user_data['note'] = ''
    else:
        await update.callback_query.edit_message_text("Enter note text:")
        return P_NOTE
    # proceed to confirm
    return await confirm_payout_prompt(update, context)

async def confirm_payout_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = context.user_data.get('note', '')
    local = context.user_data['local_amt']
    usd = context.user_data['usd_amt']
    fx = local / usd if usd else 0
    summary = (
        f"Local: {local:.2f}\n"
        f"USD Paid: {usd:.2f}\n"
        f"FX Rate: {fx:.4f}\n"
        f"Note: {note}"    
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pout_conf_yes"),
        InlineKeyboardButton("❌ No", callback_data="pout_conf_no"),
    ]])
    # reply using message or callback
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_CONFIRM

@require_unlock
async def confirm_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'pout_conf_yes':
        rec = {
            'partner_id': context.user_data['partner_id'],
            'local_amt':   context.user_data['local_amt'],
            'usd_amt':     context.user_data['usd_amt'],
            'fx_rate':     context.user_data['local_amt']/context.user_data['usd_amt'] if context.user_data['usd_amt'] else 0,
            'note':        context.user_data.get('note',''),
            'timestamp':   datetime.utcnow().isoformat()
        }
        secure_db.insert('partner_payouts', rec)
        await update.callback_query.edit_message_text(
            "✅ Payout recorded.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
        )
    else:
        await show_payout_menu(update, context)
    return ConversationHandler.END

# --- View Payouts Flow ---
async def view_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View payouts")
    await update.callback_query.answer()
    rows = secure_db.all('partner_payouts')
    if not rows:
        text = "No payouts found."
    else:
        text = "Payouts:\n"
        for r in rows:
            p = secure_db.table('partners').get(doc_id=r['partner_id'])
            name = p['name'] if p else 'Unknown'
            text += f"• [{r.doc_id}] {name}: {r['local_amt']:.2f} => {r['usd_amt']:.2f} USD\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# --- Edit Payout Flow ---
@require_unlock
async def edit_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start edit_payout")
    await update.callback_query.answer()
    partners = secure_db.all('partners')
    buttons = [InlineKeyboardButton(f"{p['name']}", callback_data=f"pout_edit_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return P_EDIT_PARTNER

async def get_edit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.rsplit('_',1)[1])
    context.user_data['partner_id'] = pid
    rows = [r for r in secure_db.all('partner_payouts') if r['partner_id']==pid]
    if not rows:
        return await show_payout_menu(update, context)
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}=>{r['usd_amt']:.2f}", callback_data=f"pout_edit_sel_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select payout to edit:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did = int(update.callback_query.data.rsplit('_',1)[1])
    rec = secure_db.table('partner_payouts').get(doc_id=did)
    context.user_data['edit_rec'] = rec
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_EDIT_LOCAL

async def get_edit_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amt = float(update.message.text)
    context.user_data['local_amt'] = amt
    await update.message.reply_text("Enter new USD paid:")
    return P_EDIT_USD

async def get_edit_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usd = float(update.message.text)
    context.user_data['usd_amt'] = usd
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 Add Note", callback_data="note_yes"),
        InlineKeyboardButton("⏭️ Skip Note", callback_data="note_skip"),
    ]])
    await update.message.reply_text("Optional: add a note?", reply_markup=kb)
    return P_EDIT_NOTE

async def get_edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data=='note_skip':
        context.user_data['note'] = context.user_data['edit_rec'].get('note','')
    else:
        await update.callback_query.edit_message_text("Enter note text:")
        return P_EDIT_NOTE
    return await confirm_edit_prompt(update, context)

async def confirm_edit_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rec0 = context.user_data['edit_rec']
    rec = {
        'partner_id': rec0['partner_id'],
        'local_amt':   context.user_data['local_amt'],
        'usd_amt':     context.user_data['usd_amt'],
        'fx_rate':     context.user_data['local_amt']/context.user_data['usd_amt'] if context.user_data['usd_amt'] else 0,
        'note':        context.user_data.get('note',''),
    }
    summary = (
        f"Local: {rec['local_amt']:.2f}\n"
        f"USD Paid: {rec['usd_amt']:.2f}\n"
        f"FX Rate: {rec['fx_rate']:.4f}\n"
        f"Note: {rec['note']}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Save", callback_data="pout_save_yes"),
        InlineKeyboardButton("❌ Cancel", callback_data="pout_save_no"),
    ]])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_EDIT_CONFIRM

@require_unlock
async def confirm_edit_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data=='pout_save_yes':
        rec0 = context.user_data['edit_rec']
        secure_db.update('partner_payouts', context.user_data, [rec0.doc_id])
        await update.callback_query.edit_message_text(
            f"✅ Payout {rec0.doc_id} updated.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
        )
    else:
        await show_payout_menu(update, context)
    return ConversationHandler.END

# --- Delete Payout Flow ---
@require_unlock
async def delete_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start delete_payout")
    await update.callback_query.answer()
    partners = secure_db.all('partners')
    buttons = [InlineKeyboardButton(f"{p['name']}", callback_data=f"pout_del_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return P_DELETE_PARTNER

async def get_delete_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.rsplit('_',1)[1])
    rows = [r for r in secure_db.all('partner_payouts') if r['partner_id']==pid]
    if not rows:
        return await show_payout_menu(update, context)
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}=>{r['usd_amt']:.2f}", callback_data=f"pout_del_sel_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select payout to delete:", reply_markup=kb)
    return P_DELETE_SELECT

async def confirm_delete_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did = int(update.callback_query.data.rsplit('_',1)[1])
    secure_db.remove('partner_payouts', [did])
    await update.callback_query.edit_message_text(
        f"✅ Payout {did} deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
    )
    return ConversationHandler.END

# --- Register Handlers ---
def register_payout_handlers(app):
    app.add_handler(CallbackQueryHandler(show_payout_menu, pattern="^payout_menu$"))

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_payout", add_payout),
            CallbackQueryHandler(add_payout, pattern="^add_payout$")
        ],
        states={
            P_PARTNER_SELECT: [CallbackQueryHandler(get_payout_partner, pattern="^pout_\d+")],
            P_LOCAL_AMT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_local)],
            P_USD_PAID:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_usd)],
            P_NOTE:           [CallbackQueryHandler(get_payout_note, pattern="^note_"), MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_note)],
            P_CONFIRM:        [CallbackQueryHandler(confirm_payout, pattern="^pout_conf_")],
        },
        fallbacks=[CommandHandler("cancel", confirm_payout)],
        per_message=False
    )
    app.add_handler(add_conv)

    app.add_handler(CallbackQueryHandler(view_payouts, pattern="^view_payout$"))

    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_payout", edit_payout),
            CallbackQueryHandler(edit_payout, pattern="^edit_payout$")
        ],
        states={
            P_EDIT_PARTNER: [CallbackQueryHandler(get_edit_partner, pattern="^pout_edit_\d+")],
            P_EDIT_SELECT:  [CallbackQueryHandler(get_edit_selection, pattern="^pout_edit_sel_\d+")],
            P_EDIT_LOCAL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_local)],
            P_EDIT_USD:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_usd)],
            P_EDIT_NOTE:    [CallbackQueryHandler(get_edit_note, pattern="^note_"), MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_note)],
            P_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_payout, pattern="^pout_save_")],
        },
        fallbacks=[CommandHandler("cancel", confirm_edit_payout)],
        per_message=False
    )
    app.add_handler(edit_conv)

    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("remove_payout", delete_payout),
            CallbackQueryHandler(delete_payout, pattern="^remove_payout$")
        ],
        states={
            P_DELETE_PARTNER: [CallbackQueryHandler(get_delete_partner, pattern="^pout_del_\d+")],
            P_DELETE_SELECT:  [CallbackQueryHandler(confirm_delete_payout, pattern="^pout_del_sel_\d+")],
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_payout)],
        per_message=False
    )
    app.add_handler(del_conv)