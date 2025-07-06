# handlers/payments.py

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

# State constants for the payment flow
(
    P_CUST_SELECT,    # choose customer
    P_LOCAL_AMT,      # enter local amount
    P_FEE_PERC,       # enter fee percentage
    P_USD_RECEIVED,   # enter USD received
    P_DATE,           # enter payment date or skip
    P_NOTE,           # optional note
    P_CONFIRM,        # confirm add
    P_VIEW,           # view flow
    P_EDIT_SELECT,    # select payment to edit
    P_EDIT_LOCAL,     # enter new local amount
    P_EDIT_FEE,       # enter new fee percentage
    P_EDIT_USD,       # enter new USD received
    P_EDIT_DATE,      # enter new date or skip
    P_EDIT_NOTE,      # optional new note
    P_EDIT_CONFIRM,   # confirm edit
    P_DELETE_SELECT,  # select payment to delete
    P_DELETE_CONFIRM  # confirm delete
) = range(17)

# --- Submenu ---
async def show_payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payment submenu")
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Payment",    callback_data="add_payment")],
        [InlineKeyboardButton("👀 View Payments", callback_data="view_payments")],
        [InlineKeyboardButton("✏️ Edit Payment",  callback_data="edit_payment")],
        [InlineKeyboardButton("🗑️ Remove Payment",callback_data="delete_payment")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text("Payments: choose an action", reply_markup=kb)

# --- Add Payment Flow ---
@require_unlock
async def add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_payment")
    await update.callback_query.answer()
    customers = secure_db.all('customers')
    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"pay_cust_{c.doc_id}") for c in customers]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a customer:", reply_markup=kb)
    return P_CUST_SELECT

async def get_payment_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data['customer_id'] = cid
    await update.callback_query.edit_message_text("Enter amount received (local currency):")
    return P_LOCAL_AMT

async def get_local_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['local_amt'] = float(update.message.text)
    await update.message.reply_text("Enter handling fee % (e.g. 5):")
    return P_FEE_PERC

async def get_fee_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fee_perc'] = float(update.message.text)
    await update.message.reply_text("Enter USD received after conversion:")
    return P_USD_RECEIVED

async def get_usd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['usd_amt'] = float(update.message.text)
    # prompt for date with skip button
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭️ Today", callback_data="date_skip")
    ]])
    await update.message.reply_text("Enter payment date (YYYY-MM-DD) or tap ⏭️ for today:", reply_markup=kb)
    return P_DATE

async def get_payment_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date_str = datetime.utcnow().date().isoformat()
    else:
        date_str = update.message.text.strip()
    context.user_data['date'] = date_str
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏭️ Skip Note", callback_data="note_skip")
    ]])
    await (update.callback_query or update.message).reply_text("Enter an optional note:", reply_markup=kb)
    return P_NOTE

async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle optional note entry, supports skip via button or text
    if update.callback_query:
        await update.callback_query.answer()
        text = update.callback_query.data
        # If skip button pressed, treat as '/skip'
        note = ''
        target = update.callback_query.message
    else:
        text = update.message.text.strip()
        note = '' if text.lower() == '/skip' else text
        target = update.message
    context.user_data['note'] = note
    # Calculate fees and rates
    local_amt = context.user_data['local_amt']
    fee_perc = context.user_data['fee_perc']
    fee_amt = local_amt * fee_perc / 100
    net_local = local_amt - fee_amt
    usd_amt = context.user_data['usd_amt']
    fx_rate = net_local / usd_amt if usd_amt else 0
    inv_rate = usd_amt / net_local if net_local else 0
    date_str = context.user_data.get('date', datetime.utcnow().date().isoformat())
    summary = (
    f"Date: {context.user_data.get('date', datetime.utcnow().date().isoformat())}
"
    f"Received: {context.user_data['local_amt']:.2f}
"
    f"Fee: {context.user_data['fee_perc']:.2f}% ({(context.user_data['local_amt'] * context.user_data['fee_perc'] / 100):.2f})
"
    f"USD Received: {context.user_data['usd_amt']:.2f}

"
    f"FX Rate: {(context.user_data['local_amt'] * (1 - context.user_data['fee_perc']/100) / context.user_data['usd_amt']):.4f}
"
    f"Inverse: {(context.user_data['usd_amt'] / (context.user_data['local_amt'] * (1 - context.user_data['fee_perc']/100))):.4f}
"
    f"Note: {context.user_data.get('note','')}"
)
"
        f"USD Received: {usd_amt:.2f}

"
        f"FX Rate: {fx_rate:.4f}
"
        f"Inverse: {inv_rate:.4f}
"
        f"Note: {note}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pay_conf_yes"),
        InlineKeyboardButton("❌ No",  callback_data="pay_conf_no")
    ]])
    await target.reply_text(summary, reply_markup=kb)
    return P_CONFIRM

@require_unlock
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'pay_conf_yes':
        rec = {
            'customer_id': context.user_data['customer_id'],
            'local_amt':   context.user_data['local_amt'],
            'fee_perc':    context.user_data['fee_perc'],
            'fee_amt':     context.user_data['local_amt'] * context.user_data['fee_perc']/100,
            'usd_amt':     context.user_data['usd_amt'],
            'fx_rate':     (context.user_data['local_amt']*(1-context.user_data['fee_perc']/100))/context.user_data['usd_amt'],
            'date':        context.user_data['date'],
            'note':        context.user_data['note'],
            'ts':          datetime.utcnow().isoformat()
        }
        secure_db.insert('customer_payments', rec)
        await update.callback_query.edit_message_text(
            "✅ Payment recorded.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
    else:
        await show_payment_menu(update, context)
    return ConversationHandler.END

# --- View Payments ---
async def view_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View payments")
    await update.callback_query.answer()
    rows = secure_db.all('customer_payments')
    text = "Payments:\n" if rows else "No payments found."
    for r in rows:
        c = secure_db.table('customers').get(doc_id=r['customer_id'])
        name = c['name'] if c else 'Unknown'
        text += f"• [{r.doc_id}] {r['date']} {name}: {r['local_amt']:.2f}=>{r['usd_amt']:.2f} USD\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# --- Edit Payment ---
@require_unlock
async def edit_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start edit_payment")
    await update.callback_query.answer()
    rows = secure_db.all('customer_payments')
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments to edit.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['date']} {r.get('local_amt',0):.2f}->", callback_data=f"edit_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select a payment to edit:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.rsplit('_',1)[1])
    rec = secure_db.table('customer_payments').get(doc_id=pid)
    context.user_data['edit_rec'] = rec
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_EDIT_LOCAL

async def get_edit_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['local_amt'] = float(update.message.text)
    await update.message.reply_text("Enter new fee %:")
    return P_EDIT_FEE

async def get_edit_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fee_perc'] = float(update.message.text)
    await update.message.reply_text("Enter new USD received:")
    return P_EDIT_USD

async def get_edit_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['usd_amt'] = float(update.message.text)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip Date", callback_data="edit_date_skip")]])
    await update.message.reply_text("Enter new date (YYYY-MM-DD) or skip:", reply_markup=kb)
    return P_EDIT_DATE

async def get_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == 'edit_date_skip':
        date_str = context.user_data['edit_rec']['date']
        await update.callback_query.answer()
    else:
        date_str = update.message.text.strip()
    context.user_data['date'] = date_str
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip Note", callback_data="edit_note_skip")]])
    await (update.callback_query or update.message).reply_text("Enter new note or skip:", reply_markup=kb)
    return P_EDIT_NOTE

async def get_edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == 'edit_note_skip':
        note = context.user_data['edit_rec'].get('note','')
        await update.callback_query.answer()
    else:
        note = update.message.text.strip()
    context.user_data['note'] = note
    # update DB
    rec = context.user_data['edit_rec']
    secure_db.update('customer_payments', {
        'local_amt': context.user_data['local_amt'],
        'fee_perc':  context.user_data['fee_perc'],
        'fee_amt':   context.user_data['local_amt']*context.user_data['fee_perc']/100,
        'usd_amt':   context.user_data['usd_amt'],
        'fx_rate':   (context.user_data['local_amt']*(1-context.user_data['fee_perc']/100))/context.user_data['usd_amt'],
        'date':      context.user_data['date'],
        'note':      note
    }, [rec.doc_id])
    await (update.message or update.callback_query).reply_text(
        f"✅ Payment [{rec.doc_id}] updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    )
    return ConversationHandler.END

# --- Delete Payment ---
@require_unlock
async def delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start delete_payment")
    await update.callback_query.answer()
    rows = secure_db.all('customer_payments')
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments to remove.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['date']}", callback_data=f"delete_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select a payment to delete:", reply_markup=kb)
    return P_DELETE_SELECT

async def confirm_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.rsplit('_',1)[1])
    secure_db.remove('customer_payments',[pid])
    await update.callback_query.edit_message_text(
        f"✅ Payment [{pid}] deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    )
    return ConversationHandler.END

# --- Register Handlers ---
def register_payment_handlers(app):
    # submenu
    app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))

    # add payment
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
            P_DATE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_date),
                             CallbackQueryHandler(get_payment_date, pattern="^date_skip$")],
            P_NOTE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note),
                             CallbackQueryHandler(get_payment_note, pattern="^note_skip$")],
            P_CONFIRM:      [CallbackQueryHandler(confirm_payment, pattern="^pay_conf_")],
        },
        fallbacks=[CommandHandler("cancel", confirm_payment)],
        per_message=False
    )
    app.add_handler(add_conv)

    # view payments
    app.add_handler(CallbackQueryHandler(view_payments, pattern="^view_payments$"))

    # edit payment
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_payment, pattern="^edit_payment$")],
        states={
            P_EDIT_SELECT: [CallbackQueryHandler(get_edit_selection, pattern="^edit_payment_")],
            P_EDIT_LOCAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_local)],
            P_EDIT_FEE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_fee)],
            P_EDIT_USD:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_usd)],
            P_EDIT_DATE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_date),
                            CallbackQueryHandler(get_edit_date, pattern="^edit_date_skip$")],
            P_EDIT_NOTE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_note),
                            CallbackQueryHandler(get_edit_note, pattern="^edit_note_skip$")],
            P_EDIT_CONFIRM:[CommandHandler("confirm_edit", lambda u,c: c), # no direct confirm button
                             ],
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_payment)],
        per_message=False
    )
    app.add_handler(edit_conv)

    # delete payment
    del_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_payment, pattern="^delete_payment$")],
        states={
            P_DELETE_SELECT:[CallbackQueryHandler(confirm_delete_payment, pattern="^delete_payment_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_payment)],
        per_message=False
    )
    app.add_handler(del_conv)
