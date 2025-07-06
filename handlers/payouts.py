# handlers/payouts.py

import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from handlers.utils import require_unlock
from secure_db import secure_db

# State constants
(
    P_PARTNER_SELECT,
    P_LOCAL_AMT,
    P_FEE_PERC,
    P_USD_PAID,
    P_NOTE,
    P_DATE,
    P_CONFIRM,
    P_EDIT_PARTNER,
    P_EDIT_SELECT,
    P_EDIT_LOCAL,
    P_EDIT_FEE,
    P_EDIT_USD,
    P_EDIT_NOTE,
    P_EDIT_DATE,
    P_EDIT_CONFIRM,
    P_DELETE_PARTNER,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM,
) = range(18)

async def show_payout_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payout submenu")
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Payout",    callback_data="add_payout")],
        [InlineKeyboardButton("👀 View Payouts", callback_data="view_payout")],
        [InlineKeyboardButton("✏️ Edit Payout",  callback_data="edit_payout")],
        [InlineKeyboardButton("🗑️ Remove Payout", callback_data="remove_payout")],
        [InlineKeyboardButton("🔙 Main Menu",    callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text(
        "Payouts: choose an action", reply_markup=kb
    )

@require_unlock
async def add_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_payout")
    await update.callback_query.answer()
    partners = secure_db.all('partners')
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners available.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p['name'], callback_data=f"pout_{p.doc_id}") for p in partners]
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
    try:
        amt = float(update.message.text)
        if amt <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid positive number.")
        return P_LOCAL_AMT
    context.user_data['local_amt'] = amt
    await update.message.reply_text("Enter handling fee % (e.g. 2.5), or 0 if none:")
    return P_FEE_PERC

async def get_payout_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee_pct = float(update.message.text)
        if fee_pct < 0 or fee_pct >= 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Enter a fee percentage between 0 and 100.")
        return P_FEE_PERC
    data = context.user_data
    data['fee_perc'] = fee_pct
    data['fee_amt'] = data['local_amt'] * fee_pct / 100.0
    await update.message.reply_text(
        f"Fee: {fee_pct:.2f}% → {data['fee_amt']:.2f}. Now enter USD paid:"
    )
    return P_USD_PAID

async def get_payout_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return P_USD_PAID
    context.user_data['usd_amt'] = usd
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 Add Note", callback_data="note_yes"),
        InlineKeyboardButton("⏭️ Skip Note", callback_data="note_skip"),
    ]])
    await update.message.reply_text("Optional: add a note?", reply_markup=kb)
    return P_NOTE

async def get_payout_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.data == 'note_skip':
            context.user_data['note'] = ''
            return await confirm_payout_prompt(update, context)
        else:
            await update.callback_query.edit_message_text("Enter note text:")
            return P_NOTE
    else:
        context.user_data['note'] = update.message.text.strip()
        return await confirm_payout_prompt(update, context)

async def confirm_payout_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    local   = data['local_amt']
    fee_pct = data.get('fee_perc', 0)
    fee_amt = data.get('fee_amt', 0)
    usd     = data['usd_amt']
    net     = local - fee_amt
    fx      = net / usd if usd else 0
    summary = (
        f"Local: {local:.2f}\n"
        f"Fee: {fee_pct:.2f}% ({fee_amt:.2f})\n"
        f"USD Paid: {usd:.2f}\n"
        f"FX Rate: {fx:.4f}\n"
        f"Note: {data.get('note','')}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pout_conf_yes"),
        InlineKeyboardButton("❌ No",  callback_data="pout_conf_no"),
    ]])
    await update.callback_query.edit_message_text(summary, reply_markup=kb)
    return P_CONFIRM

@require_unlock
async def confirm_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'pout_conf_yes':
        data = context.user_data
        rec = {
            'partner_id': data['partner_id'],
            'local_amt':  data['local_amt'],
            'fee_perc':   data['fee_perc'],
            'fee_amt':    data['fee_amt'],
            'usd_amt':    data['usd_amt'],
            'fx_rate':    (data['local_amt']-data['fee_amt'])/data['usd_amt'] if data['usd_amt'] else 0,
            'note':       data.get('note',''),
            'timestamp':  datetime.utcnow().isoformat(),
        }
        secure_db.insert('partner_payouts', rec)
        await update.callback_query.edit_message_text(
            f"✅ Payout of {data['local_amt']:.2f} recorded.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
        )
    else:
        await show_payout_menu(update, context)
    return ConversationHandler.END

async def view_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View payouts")
    await update.callback_query.answer()
    rows = secure_db.all('partner_payouts')
    if not rows:
        text = "No payouts found."
    else:
        lines = []
        for r in rows:
            p = secure_db.table('partners').get(doc_id=r['partner_id'])
            name = p['name'] if p else 'Unknown'
            fee_pct = r.get('fee_perc', 0)
            fee_amt = r.get('fee_amt', 0)
            lines.append(
                f"[{r.doc_id}] {name}: {r['local_amt']:.2f} "
                f"(fee {fee_pct:.2f}%={fee_amt:.2f}) => {r['usd_amt']:.2f} USD"
            )
        text = "Payouts:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# --- Edit Payout Flow ---
@require_unlock
async def edit_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all('partners')
    buttons = [
        InlineKeyboardButton(p['name'], callback_data=f"pout_edit_{p.doc_id}")
        for p in partners
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text(
        "Select partner to edit:", reply_markup=kb
    )
    return P_EDIT_PARTNER

async def get_edit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split('_')[-1])
    context.user_data['edit'] = {'partner_id': pid}
    rows = [r for r in secure_db.all('partner_payouts') if r['partner_id'] == pid]
    buttons = [
        InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}",
                             callback_data=f"pout_edit_sel_{r.doc_id}")
        for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text(
        "Select payout record:", reply_markup=kb
    )
    return P_EDIT_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did = int(update.callback_query.data.split('_')[-1])
    rec = secure_db.table('partner_payouts').get(doc_id=did)
    e = rec.copy()
    e['doc_id'] = did
    context.user_data['edit'] = e
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_EDIT_LOCAL

async def get_edit_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text)
        if amt <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Enter a valid positive number.")
        return P_EDIT_LOCAL
    context.user_data['edit']['local_amt'] = amt
    await update.message.reply_text("Enter new handling fee % (e.g. 2.5), or 0 if none:")
    return P_EDIT_FEE

async def get_edit_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pct = float(update.message.text)
        if not (0 <= pct < 100):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Enter a fee percentage between 0 and 100.")
        return P_EDIT_FEE
    e = context.user_data['edit']
    e['fee_perc'] = pct
    e['fee_amt']  = e['local_amt'] * pct / 100.0
    await update.message.reply_text("Enter new USD paid:")
    return P_EDIT_USD

async def get_edit_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Enter a valid number.")
        return P_EDIT_USD
    context.user_data['edit']['usd_amt'] = usd
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="note_skip")]])
    await update.message.reply_text("Enter an optional note or press Skip:", reply_markup=kb)
    return P_EDIT_NOTE

async def get_edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    e = context.user_data['edit']
    if update.callback_query and update.callback_query.data == 'note_skip':
        await update.callback_query.answer()
        e['note'] = ''
    else:
        e['note'] = update.message.text.strip()
    today = datetime.now().strftime('%d%m%Y')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="date_skip")]])
    prompt = f"Enter new payout date in DDMMYYYY or press Skip for today ({today}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return P_EDIT_DATE

async def get_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    e = context.user_data['edit']
    if update.callback_query and update.callback_query.data == 'date_skip':
        await update.callback_query.answer()
        ds = datetime.now().strftime('%d%m%Y')
    else:
        ds = update.message.text.strip()
        try:
            datetime.strptime(ds, '%d%m%Y')
        except ValueError:
            await update.message.reply_text("Invalid. Use DDMMYYYY.")
            return P_EDIT_DATE
    e['date'] = ds

    local, pct, fee_amt, usd = (
        e['local_amt'], e['fee_perc'], e['fee_amt'], e['usd_amt']
    )
    net = local - fee_amt
    fx  = net / usd if usd else 0.0
    summary = (
        f"Local: {local:.2f}\n"
        f"Fee: {pct:.2f}% ({fee_amt:.2f})\n"
        f"USD Paid: {usd:.2f}\n"
        f"FX Rate: {fx:.4f}\n"
        f"Note: {e.get('note','')}\n"
        f"Date: {e['date']}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Save", callback_data="pout_save_yes"),
                                 InlineKeyboardButton("❌ Cancel", callback_data="pout_save_no")]])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_EDIT_CONFIRM

@require_unlock
async def confirm_edit_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    e = context.user_data.get('edit')
    if not e:
        await show_payout_menu(update, context)
        return ConversationHandler.END

    if update.callback_query.data == 'pout_save_yes':
        e['fx_rate'] = (e['local_amt'] - e['fee_amt'])/e['usd_amt'] if e['usd_amt'] else 0.0
        secure_db.update('partner_payouts', e, [e['doc_id']])
        await update.callback_query.edit_message_text(
            f"✅ Payout {e['doc_id']} updated.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]
            ])
        )
    else:
        await show_payout_menu(update, context)

    context.user_data.pop('edit', None)
    return ConversationHandler.END


# --- Delete Payout (with confirmation) ---
@require_unlock
async def delete_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = secure_db.all('partner_payouts')
    buttons = [
        InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}",
                             callback_data=f"pout_del_{r.doc_id}")
        for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text(
        "Select payout to delete:", reply_markup=kb
    )
    return P_DELETE_PARTNER

async def get_delete_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did = int(update.callback_query.data.split('_')[-1])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=f"pout_del_yes_{did}"),
        InlineKeyboardButton("❌ No",  callback_data="payout_menu")
    ]])
    await update.callback_query.edit_message_text(
        f"Confirm delete payout #{did}?", reply_markup=kb
    )
    return P_DELETE_SELECT

async def confirm_delete_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = update.callback_query.data
    if data.startswith('pout_del_yes_'):
        did = int(data.split('_')[-1])
        secure_db.remove('partner_payouts', [did])
        await update.callback_query.edit_message_text(
            f"✅ Payout {did} deleted.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]
            ])
        )
    else:
        await show_payout_menu(update, context)
    return ConversationHandler.END


# --- Register Handlers ---
def register_payout_handlers(app):
    app.add_handler(CallbackQueryHandler(show_payout_menu, pattern="^payout_menu$"))

    add_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_payout, pattern="^add_payout$"),
            CommandHandler("add_payout", add_payout)
        ],
        states={
            P_PARTNER_SELECT: [CallbackQueryHandler(get_payout_partner, pattern="^pout_\\d+$")],
            P_LOCAL_AMT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_local)],
            P_FEE_PERC:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_fee)],
            P_USD_PAID:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_usd)],
            P_NOTE:           [
                CallbackQueryHandler(get_payout_note, pattern="^note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_note)
            ],
            P_DATE:           [
                CallbackQueryHandler(get_payout_date, pattern="^date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_date)
            ],
            P_CONFIRM:        [CallbackQueryHandler(confirm_payout, pattern="^pout_conf_")]
        },
        fallbacks=[CommandHandler("cancel", show_payout_menu)],
        per_message=False
    )
    app.add_handler(add_conv)

    app.add_handler(CallbackQueryHandler(view_payouts, pattern="^view_payout$"))

    edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_payout, pattern="^edit_payout$"),
            CommandHandler("edit_payout", edit_payout)
        ],
        states={
            P_EDIT_PARTNER: [CallbackQueryHandler(get_edit_partner, pattern="^pout_edit_\\d+$")],
            P_EDIT_SELECT:  [CallbackQueryHandler(get_edit_selection, pattern="^pout_edit_sel_\\d+$")],
            P_EDIT_LOCAL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_local)],
            P_EDIT_FEE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_fee)],
            P_EDIT_USD:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_usd)],
            P_EDIT_NOTE:    [
                CallbackQueryHandler(get_edit_note, pattern="^note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_note)
            ],
            P_EDIT_DATE:    [
                CallbackQueryHandler(get_edit_date, pattern="^date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_date)
            ],
            P_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_payout, pattern="^pout_save_")]
        },
        fallbacks=[CommandHandler("cancel", show_payout_menu)],
        per_message=False
    )
    app.add_handler(edit_conv)

    del_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(delete_payout, pattern="^delete_payout$"),
            CommandHandler("delete_payout", delete_payout)
        ],
        states={
            P_DELETE_PARTNER: [CallbackQueryHandler(get_delete_partner, pattern="^pout_del_\\d+$")],
            P_DELETE_SELECT:  [CallbackQueryHandler(confirm_delete_payout, pattern="^(pout_del_yes_\\d+|payout_menu)$")]
        },
        fallbacks=[CommandHandler("cancel", show_payout_menu)],
        per_message=False
    )
    app.add_handler(del_conv)