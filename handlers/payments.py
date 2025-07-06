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
    P_CUST_SELECT,
    P_LOCAL_AMT,
    P_FEE_PERC,
    P_USD_RECEIVED,
    P_DATE,
    P_NOTE,
    P_CONFIRM,
    P_EDIT_SELECT,
    P_EDIT_LOCAL,
    P_EDIT_FEE,
    P_EDIT_USD,
    P_EDIT_DATE,
    P_EDIT_NOTE,
    P_EDIT_CONFIRM,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM,
) = range(16)

# --- Submenu for Payments ---
async def show_payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payment submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Payment",    callback_data="add_payment")],
            [InlineKeyboardButton("👀 View Payments", callback_data="view_payments")],
            [InlineKeyboardButton("✏️ Edit Payment",  callback_data="edit_payment")],
            [InlineKeyboardButton("🗑️ Remove Payment",callback_data="remove_payment")],
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
        f"{r['name']} ({r['currency']})", callback_data=f"pay_cust_{r.doc_id}" )
        for r in rows
    ]
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
    # Prompt for date with skip button
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Skip (today)", callback_data="date_skip")
    ]])
    await update.message.reply_text(
        "Enter the payment date (YYYY-MM-DD) or tap Skip:", reply_markup=kb
    )
    return P_DATE

async def get_payment_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handles both callback skip and text entry
    if update.callback_query:
        await update.callback_query.answer()
        date_str = datetime.utcnow().date().isoformat()
    else:
        date_str = update.message.text.strip()
    context.user_data['date'] = date_str
    await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)(
        "Enter an optional note:",
    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Skip Note", callback_data="note_skip")]])
    )
    return P_NOTE

async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        note = ''
    else:
        note = update.message.text.strip()
    context.user_data['note'] = note
    # Build summary
    local = context.user_data['local_amt']
    fee_perc = context.user_data['fee_perc']
    fee_amt = local * fee_perc/100
    net_local = local - fee_amt
    usd = context.user_data['usd_amt']
    fx = net_local / usd
    inv = usd / net_local
    date_str = context.user_data.get('date')
    summary = (
        f"Date: {date_str}\n"
        f"Received: {local:.2f}\n"
        f"Fee: {fee_perc:.2f}% ({fee_amt:.2f})\n"
        f"USD: {usd:.2f}\n"
        f"FX: {fx:.4f}, Inv: {inv:.4f}\n"
        f"Note: {note}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pay_conf_yes"),
        InlineKeyboardButton("❌ No",  callback_data="pay_conf_no")
    ]])
    await (update.message.reply_text if not update.callback_query else update.callback_query.edit_message_text)(summary, reply_markup=kb)
    return P_CONFIRM

@require_unlock
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'pay_conf_yes':
        rec = {
            'customer_id': context.user_data['customer_id'],
            'local_amt':   context.user_data['local_amt'],
            'fee_perc':    context.user_data['fee_perc'],
            'fee_amt':     context.user_data['local_amt']*context.user_data['fee_perc']/100,
            'usd_amt':     context.user_data['usd_amt'],
            'fx_rate':     (context.user_data['local_amt']*(1-context.user_data['fee_perc']/100))/context.user_data['usd_amt'],
            'date':        context.user_data['date'],
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

# View, Edit, Delete flows remain unchanged

# --- Register Handlers ---
def register_payment_handlers(app):
    app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))
    app.add_handler(add_conv)
    app.add_handler(CallbackQueryHandler(view_payments, pattern="^view_payments$"))
    app.add_handler(edit_conv)
    app.add_handler(del_conv)

# end of handlers/payments.py


