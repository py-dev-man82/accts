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
    P_CUST_SELECT,    # Select customer
    P_LOCAL_AMT,      # Enter local amount
    P_FEE_PERC,       # Enter fee percent
    P_USD_RECEIVED,   # Enter USD received
    P_DATE,           # Enter payment date or skip
    P_NOTE,           # Enter optional note or skip
    P_CONFIRM,        # Confirm entry
    P_EDIT_SELECT,    # Select payment to edit
    P_EDIT_LOCAL,     # Enter new local amount
    P_EDIT_FEE,       # Enter new fee percent
    P_EDIT_USD,       # Enter new USD received
    P_EDIT_DATE,      # Enter new date or skip
    P_EDIT_NOTE,      # Enter new note or skip
    P_EDIT_CONFIRM,   # Confirm edit
    P_DELETE_SELECT,  # Select payment to delete
    P_DELETE_CONFIRM  # Confirm deletion
) = range(16)

# --- Payments Submenu ---
async def show_payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payment submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Payment", callback_data="add_payment")],
            [InlineKeyboardButton("👀 View Payments", callback_data="view_payments")],
            [InlineKeyboardButton("✏️ Edit Payment", callback_data="edit_payment")],
            [InlineKeyboardButton("🗑️ Remove Payment", callback_data="delete_payment")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])
        await update.callback_query.edit_message_text(
            "Payments: choose an action", reply_markup=kb
        )

# --- Add Payment Flow ---
@require_unlock
async def add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_payment")
    await update.callback_query.answer()
    rows = secure_db.all('customers')
    buttons = [InlineKeyboardButton(
        f"{r['name']} ({r['currency']})", callback_data=f"pay_cust_{r.doc_id}"
    ) for r in rows]
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
    amt = float(update.message.text)
    context.user_data['local_amt'] = amt
    await update.message.reply_text("Enter handling fee % (e.g. 5):")
    return P_FEE_PERC

async def get_fee_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    perc = float(update.message.text)
    context.user_data['fee_perc'] = perc
    await update.message.reply_text("Enter USD received after conversion:")
    return P_USD_RECEIVED

async def get_usd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usd = float(update.message.text)
    context.user_data['usd_amt'] = usd
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Skip (today)", callback_data="date_skip")
    ]])
    await update.message.reply_text(
        "Enter payment date (YYYY-MM-DD) or press Skip:", reply_markup=kb
    )
    return P_DATE

async def get_payment_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date_str = datetime.utcnow().date().isoformat()
    else:
        date_str = update.message.text.strip()
    context.user_data['date'] = date_str
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Skip note", callback_data="note_skip")
    ]])
    await (update.callback_query or update.message).reply_text(
        "Enter an optional note or Skip:", reply_markup=kb
    )
    return P_NOTE

async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        note = ''
    else:
        note = update.message.text.strip()
    context.user_data['note'] = note
    local = context.user_data['local_amt']
    perc = context.user_data['fee_perc']
    fee_amt = local * perc / 100
    net_local = local - fee_amt
    usd = context.user_data['usd_amt']
    fx_rate = net_local / usd
    inv_rate = usd / net_local
    date_str = context.user_data.get('date', datetime.utcnow().date().isoformat())
    summary = (
        f"Date: {date_str}\n"
        f"Received: {local:.2f}\n"
        f"Fee: {perc:.2f}% ({fee_amt:.2f})\n"
        f"USD Received: {usd:.2f}\n\n"
        f"FX Rate: {fx_rate:.4f}\n"
        f"Inverse: {inv_rate:.4f}\n"
        f"Note: {note}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pay_conf_yes"),
        InlineKeyboardButton("❌ No", callback_data="pay_conf_no")
    ]])
    await (update.callback_query or update.message).reply_text(summary, reply_markup=kb)
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
            'date':        context.user_data.get('date', datetime.utcnow().date().isoformat()),
            'note':        context.user_data['note'],
            'timestamp':   datetime.utcnow().isoformat()
        }
        secure_db.insert('customer_payments', rec)
        await update.callback_query.edit_message_text(
            "✅ Payment recorded.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
    else:
        await show_payment_menu(update, context)
    return ConversationHandler.END

# --- View Payments Flow ---
async def view_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View payments")
    await update.callback_query.answer()
    rows = secure_db.all('customer_payments')
    if not rows:
        text = "No payments found."
    else:
        text = "Payments:\n"
        for r in rows:
            cust = secure_db.table('customers').get(doc_id=r['customer_id'])
            name = cust['name'] if cust else 'Unknown'
            text += f"• [{r.doc_id}] {name}: {r['local_amt']:.2f} => {r['usd_amt']:.2f} USD (Date: {r.get('date')})\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# --- Edit Payment Flow ---
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
    buttons = [InlineKeyboardButton(
        f"[{r.doc_id}] {r['local_amt']:.2f}=>{r['usd_amt']:.2f}", callback_data=f"edit_payment_{r.doc_id}"
    ) for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a payment to edit:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.rsplit('_',1)[1])
    rec = secure_db.table('customer_payments').get(doc_id=cid)
    context.user_data['edit_payment'] = rec
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_EDIT_LOCAL

# Subsequent handlers reuse the same logic (get_local_amount, get_fee_percent, etc.), but write back via update instead of insert
# ...

# --- Delete Payment Flow ---
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
    buttons = [InlineKeyboardButton(
        f"[{r.doc_id}] {r['local_amt']:.2f}=>{r['usd_amt']:.2f}", callback_data=f"delete_payment_{r.doc_id}"
    ) for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a payment to delete:", reply_markup=kb)
    return P_DELETE_SELECT

async def confirm_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did = int(update.callback_query.data.rsplit('_',1)[1])
    secure_db.remove('customer_payments',[did])
    await update.callback_query.edit_message_text(
        f"✅ Payment {did} deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    )
    return ConversationHandler.END

# --- Register Handlers ---
def register_payment_handlers(app):
    app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_payment", add_payment),
            CallbackQueryHandler(add_payment, pattern="^add_payment$")
        ],
        states={
            P_CUST_SELECT:   [CallbackQueryHandler(get_payment_customer, pattern="^pay_cust_")],
            P_LOCAL_AMT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_local_amount)],
            P_FEE_PERC:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fee_percent)],
            P_USD_RECEIVED:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_usd_received)],
            P_DATE:          [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_date),
                               CallbackQueryHandler(get_payment_date, pattern="^date_skip$")],
            P_NOTE:          [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note),
                               CallbackQueryHandler(get_payment_note, pattern="^note_skip$")],
            P_CONFIRM:       [CallbackQueryHandler(confirm_payment, pattern="^pay_conf_")],
        },
        fallbacks=[CommandHandler("cancel", confirm_payment)],
        per_message=False
    )
    app.add_handler(add_conv)

    app.add_handler(CallbackQueryHandler(view_payments, pattern="^view_payments$"))

    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_payment", edit_payment),
            CallbackQueryHandler(edit_payment, pattern="^edit_payment$")
        ],
        states={
            P_EDIT_SELECT:  [CallbackQueryHandler(get_edit_selection, pattern="^edit_payment_")],
            P_EDIT_LOCAL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_local_amount)],
            P_EDIT_FEE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fee_percent)],
            P_EDIT_USD:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_usd_received)],
            P_EDIT_DATE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_date),
                              CallbackQueryHandler(get_payment_date, pattern="^date_skip$")],
            P_EDIT_NOTE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note),
                              CallbackQueryHandler(get_payment_note, pattern="^note_skip$")],
            P_EDIT_CONFIRM:[CallbackQueryHandler(confirm_payment, pattern="^pay_conf_")],
        },
        fallbacks=[CommandHandler("cancel", confirm_payment)],
        per_message=False
    )
    app.add_handler(edit_conv)

    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("delete_payment", delete_payment),
            CallbackQueryHandler(delete_payment, pattern="^delete_payment$")
        ],
        states={
            P_DELETE_SELECT: [CallbackQueryHandler(confirm_delete_payment, pattern="^delete_payment_")],
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_payment)],
        per_message=False
    )
    app.add_handler(del_conv)
