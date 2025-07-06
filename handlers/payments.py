# handlers/payments.py

import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

from handlers.utils import require_unlock
from secure_db import secure_db

# ────────────────────────────────────────────────────────────
#  Conversation state constants
# ────────────────────────────────────────────────────────────
(
    P_CUST_SELECT,
    P_LOCAL_AMT,
    P_FEE_PERC,
    P_USD_RECEIVED,
    P_NOTE,
    P_DATE,            # 🆕 Added for custom date
    P_CONFIRM,
    P_EDIT_CUST_SELECT,
    P_EDIT_SELECT,
    P_EDIT_LOCAL,
    P_EDIT_FEE,
    P_EDIT_USD,
    P_EDIT_NOTE,
    P_EDIT_DATE,       # 🆕 Added for custom date edit
    P_EDIT_CONFIRM,
    P_DELETE_CUST_SELECT,
    P_DELETE_SELECT,
) = range(17)  # ✅ Corrected count (17 items)


# ────────────────────────────────────────────────────────────
#  Sub-menu
# ────────────────────────────────────────────────────────────
async def show_payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payment submenu")
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add",    callback_data="add_payment")],
        [InlineKeyboardButton("👀 View",   callback_data="view_payment")],
        [InlineKeyboardButton("✏️ Edit",   callback_data="edit_payment")],
        [InlineKeyboardButton("🗑️ Remove", callback_data="delete_payment")],
        [InlineKeyboardButton("🔙 Main",   callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text("Payments: choose an action", reply_markup=kb)


# ======================================================================
#                              ADD FLOW
# ======================================================================
@require_unlock
async def add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_payment")
    await update.callback_query.answer()
    rows = secure_db.all('customers')
    buttons = [
        InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"pay_cust_{r.doc_id}")
        for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return P_CUST_SELECT


async def get_payment_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data['customer_id'] = cid
    await update.callback_query.edit_message_text("Enter amount received (local currency):")
    return P_LOCAL_AMT


async def get_local_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text)
        assert amt > 0
    except:
        await update.message.reply_text("Positive number please.")
        return P_LOCAL_AMT
    context.user_data['local_amt'] = amt
    await update.message.reply_text("Enter handling fee %:")
    return P_FEE_PERC


async def get_fee_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee = float(update.message.text)
        assert 0 <= fee < 100
    except:
        await update.message.reply_text("Enter a fee percentage between 0 and 99.")
        return P_FEE_PERC
    context.user_data['fee_perc'] = fee
    await update.message.reply_text("Enter USD received:")
    return P_USD_RECEIVED


async def get_usd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text)
    except:
        await update.message.reply_text("Number please.")
        return P_USD_RECEIVED
    context.user_data['usd_amt'] = usd
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="note_skip")]])
    await update.message.reply_text("Enter an optional note or press Skip:", reply_markup=kb)
    return P_NOTE


async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        note = ""
    else:
        note = update.message.text.strip()
    context.user_data['note'] = note

    # prompt for custom date
    today = datetime.now().strftime('%d%m%Y')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="date_skip")]])
    prompt = f"Enter payment date DDMMYYYY or press Skip for today ({today}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return P_DATE


async def get_payment_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:  # skip
        await update.callback_query.answer()
        date_str = datetime.now().strftime('%d%m%Y')
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, '%d%m%Y')
        except ValueError:
            await update.message.reply_text("Format DDMMYYYY please.")
            return P_DATE
    context.user_data['date'] = date_str
    return await confirm_payment_prompt(update, context)


async def confirm_payment_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    fee_amt = d['local_amt'] * d['fee_perc'] / 100
    net = d['local_amt'] - fee_amt
    fx = net / d['usd_amt'] if d['usd_amt'] else 0
    summary = (f"Received: {d['local_amt']:.2f}\n"
               f"Fee: {d['fee_perc']:.2f}% ({fee_amt:.2f})\n"
               f"USD Recv: {d['usd_amt']:.2f}\n"
               f"FX Rate: {fx:.4f}\n"
               f"Note: {d.get('note') or '—'}\n"
               f"Date: {d['date']}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="pay_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="pay_conf_no")]
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_CONFIRM


@require_unlock
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    editing = 'edit_payment' in context.user_data
    if update.callback_query.data == 'pay_conf_yes':
        d = context.user_data
        rec = {
            'customer_id': d.get('customer_id') if not editing else context.user_data['edit_payment']['customer_id'],
            'local_amt':   d['local_amt'],
            'fee_perc':    d['fee_perc'],
            'fee_amt':     d['local_amt'] * d['fee_perc'] / 100,
            'usd_amt':     d['usd_amt'],
            'fx_rate':     (d['local_amt'] - d['local_amt'] * d['fee_perc'] / 100) / d['usd_amt'] if d['usd_amt'] else 0,
            'note':        d['note'],
            'date':        d['date'],
            'timestamp':   datetime.utcnow().isoformat()
        }
        if editing:
            old = context.user_data['edit_payment']
            secure_db.update('customer_payments', rec, [old.doc_id])
            del context.user_data['edit_payment']
            msg = f"✅ Payment #{old.doc_id} updated."
        else:
            secure_db.insert('customer_payments', rec)
            msg = "✅ Payment recorded."

        await update.callback_query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
    else:
        await show_payment_menu(update, context)
    return ConversationHandler.END


# ======================================================================
#                              EDIT FLOW
# ======================================================================
@require_unlock
async def start_edit_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = secure_db.all('customers')
    buttons = [InlineKeyboardButton(u['name'], callback_data=f"edit_user_{u.doc_id}") for u in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Choose customer:", reply_markup=kb)
    return P_EDIT_CUST_SELECT


async def list_user_payments_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data['customer_id'] = cid
    rows = [r for r in secure_db.all('customer_payments') if r['customer_id'] == cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments for this customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}->{r['usd_amt']:.2f}", callback_data=f"edit_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select payment:", reply_markup=kb)
    return P_EDIT_SELECT


async def get_payment_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    rec = secure_db.table('customer_payments').get(doc_id=pid)
    context.user_data.update({
        'edit_payment': rec,
        'local_amt':    rec['local_amt'],
        'fee_perc':     rec['fee_perc'],
        'usd_amt':      rec['usd_amt'],
        'note':         rec.get('note', ''),
        'date':         rec.get('date', datetime.now().strftime('%d%m%Y'))
    })
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_EDIT_LOCAL


async def get_edit_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text)
        assert amt > 0
    except:
        await update.message.reply_text("Positive number please.")
        return P_EDIT_LOCAL
    context.user_data['local_amt'] = amt
    await update.message.reply_text("Enter new handling fee %:")
    return P_EDIT_FEE


async def get_edit_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee = float(update.message.text)
        assert 0 <= fee < 100
    except:
        await update.message.reply_text("Enter a fee percentage between 0 and 99.")
        return P_EDIT_FEE
    context.user_data['fee_perc'] = fee
    await update.message.reply_text("Enter new USD received:")
    return P_EDIT_USD


async def get_edit_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text)
    except:
        await update.message.reply_text("Number please.")
        return P_EDIT_USD
    context.user_data['usd_amt'] = usd
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="note_skip")]])
    await update.message.reply_text("Enter an optional note or press Skip:", reply_markup=kb)
    return P_EDIT_NOTE


async def get_edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        note = ""
    else:
        note = update.message.text.strip()
    context.user_data['note'] = note
    today = datetime.now().strftime('%d%m%Y')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="edate_skip")]])
    prompt = f"Enter payment date DDMMYYYY or press Skip for today ({today}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return P_EDIT_DATE


async def get_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date_str = datetime.now().strftime('%d%m%Y')
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, '%d%m%Y')
        except ValueError:
            await update.message.reply_text("Format DDMMYYYY please.")
            return P_EDIT_DATE
    context.user_data['date'] = date_str
    return await confirm_payment_prompt(update, context)


# ======================================================================
#                              VIEW FLOW
# ======================================================================
async def view_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = secure_db.all('customer_payments')
    if not rows:
        text = "No payments found."
    else:
        lines = []
        for r in rows:
            cust = secure_db.table('customers').get(doc_id=r['customer_id'])
            name = cust['name'] if cust else "Unknown"
            lines.append(f"[{r.doc_id}] {name}: {r['local_amt']:.2f} → {r['usd_amt']:.2f} USD on {r.get('date','')} | Note: {r.get('note','')}")
        text = "Payments:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)


# ======================================================================
#                              DELETE FLOW
# ======================================================================
@require_unlock
async def start_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = secure_db.all('customers')
    buttons = [InlineKeyboardButton(u['name'], callback_data=f"del_user_{u.doc_id}") for u in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Choose customer:", reply_markup=kb)
    return P_DELETE_CUST_SELECT


async def list_user_payments_for_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    rows = [r for r in secure_db.all('customer_payments') if r['customer_id'] == cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments for this customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}->{r['usd_amt']:.2f}", callback_data=f"delete_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select to delete:", reply_markup=kb)
    return P_DELETE_SELECT


async def confirm_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did = int(update.callback_query.data.split("_")[-1])
    secure_db.remove('customer_payments', [did])
    await update.callback_query.edit_message_text(
        f"✅ Payment {did} deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    )
    return ConversationHandler.END


# ======================================================================
#                              REGISTER HANDLERS
# ======================================================================
def register_payment_handlers(app):
    app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))

    # Add
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_payment", add_payment),
            CallbackQueryHandler(add_payment, pattern="^add_payment$")
        ],
        states={
            P_CUST_SELECT:  [CallbackQueryHandler(get_payment_customer, pattern="^pay_cust_")],
            P_LOCAL_AMT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_local_amount)],
            P_FEE_PERC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fee_percent)],
            P_USD_RECEIVED: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_usd_received)],
            P_NOTE:         [
                CallbackQueryHandler(get_payment_note, pattern="^note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note)
            ],
            P_DATE:         [
                CallbackQueryHandler(get_payment_date, pattern="^date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_date)
            ],
            P_CONFIRM:      [CallbackQueryHandler(confirm_payment, pattern="^pay_conf_")],
        },
        fallbacks=[CommandHandler("cancel", show_payment_menu)],
        per_message=False
    )
    app.add_handler(add_conv)

    # View
    app.add_handler(CallbackQueryHandler(view_payments, pattern="^view_payment$"))

    # Edit
    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_payment", start_edit_payment),
            CallbackQueryHandler(start_edit_payment, pattern="^edit_payment$")
        ],
        states={
            P_EDIT_CUST_SELECT: [CallbackQueryHandler(list_user_payments_for_edit, pattern="^edit_user_")],
            P_EDIT_SELECT:      [CallbackQueryHandler(get_payment_edit_selection, pattern="^edit_payment_")],
            P_EDIT_LOCAL:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_local)],
            P_EDIT_FEE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_fee)],
            P_EDIT_USD:         [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_usd)],
            P_EDIT_NOTE:        [
                CallbackQueryHandler(get_edit_note, pattern="^note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_note)
            ],
            P_EDIT_DATE:        [
                CallbackQueryHandler(get_edit_date, pattern="^edate_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_date)
            ],
            P_EDIT_CONFIRM:     [CallbackQueryHandler(confirm_payment, pattern="^pay_conf_")],
        },
        fallbacks=[CommandHandler("cancel", show_payment_menu)],
        per_message=False
    )
    app.add_handler(edit_conv)

    # Delete
    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("delete_payment", start_delete_payment),
            CallbackQueryHandler(start_delete_payment, pattern="^delete_payment$")
        ],
        states={
            P_DELETE_CUST_SELECT: [CallbackQueryHandler(list_user_payments_for_delete, pattern="^del_user_")],
            P_DELETE_SELECT:      [CallbackQueryHandler(confirm_delete_payment, pattern="^delete_payment_")],
        },
        fallbacks=[CommandHandler("cancel", show_payment_menu)],
        per_message=False
    )
    app.add_handler(del_conv)