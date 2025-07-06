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
    P_NOTE,
    P_CONFIRM,
    P_EDIT_SELECT,
    P_EDIT_FIELD,
    P_EDIT_VALUE,
    P_EDIT_CONFIRM,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM,
) = range(12)

# --- Submenu for Payment Management ---
async def show_payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payment submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Payment",    callback_data="add_payment")],
            [InlineKeyboardButton("👀 View Payments", callback_data="view_payments")],
            [InlineKeyboardButton("✏️ Edit Payment", callback_data="edit_payment")],
            [InlineKeyboardButton("🗑️ Remove Payment", callback_data="remove_payment")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])
        await update.callback_query.edit_message_text(
            "Payment Management: choose an action",
            reply_markup=kb
        )

# --- Add Payment Flow ---
@require_unlock
async def add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_payment")
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Select a customer:")
    else:
        await update.message.reply_text("Select a customer:")
    rows = secure_db.all('customers')
    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"cust_pay_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await (update.callback_query or update.message).reply_text("Customers:", reply_markup=kb)
    return P_CUST_SELECT

async def get_payment_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_payment_customer: %s", update.callback_query.data)
    await update.callback_query.answer()
    cid = int(update.callback_query.data.rsplit("_",1)[1])
    context.user_data['pay_cust_id'] = cid
    cust = secure_db.table('customers').get(doc_id=cid)
    context.user_data['pay_cust_cur'] = cust['currency']
    await update.callback_query.edit_message_text("Enter amount received in local currency:")
    return P_LOCAL_AMT

async def get_payment_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_payment_local: %s", update.message.text)
    local = float(update.message.text.strip())
    context.user_data['pay_local_amt'] = local
    await update.message.reply_text("Enter handling fee % (e.g. 5 for 5%):")
    return P_FEE_PERC

async def get_payment_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_payment_fee: %s", update.message.text)
    fee_perc = float(update.message.text.strip())
    context.user_data['pay_fee_perc'] = fee_perc
    await update.message.reply_text("Enter USD amount actually received:")
    return P_USD_RECEIVED

async def get_usd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_usd_received: %s", update.message.text)
    usd = float(update.message.text.strip())
    context.user_data['pay_usd_received'] = usd
    await update.message.reply_text(
        "Enter an optional note for this payment (or send /skip to leave blank):"
    )
    return P_NOTE

async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == '/skip':
        context.user_data['pay_note'] = ''
    else:
        context.user_data['pay_note'] = text
    # Build summary
    local_amt = context.user_data['pay_local_amt']
    fee_perc = context.user_data['pay_fee_perc']
    fee_amt = local_amt * fee_perc/100
    net_local = local_amt - fee_amt
    usd_received = context.user_data['pay_usd_received']
    fx_rate = net_local / usd_received
    inv_rate = usd_received / net_local
    cur = context.user_data['pay_cust_cur']
    summary = (
        f"Received: {local_amt:.2f} {cur}\n"
        f"Fee: {fee_perc}% ({fee_amt:.2f} {cur})\n"
        f"USD Received: {usd_received:.2f} USD\n\n"
        f"FX Rate: {fx_rate:.4f} {cur}/USD\n"
        f"Inverse: {inv_rate:.4f} USD/{cur}\n"
        f"Note: {context.user_data.get('pay_note','')}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Save", callback_data="pay_yes"),
        InlineKeyboardButton("❌ Cancel", callback_data="pay_no")
    ]])
    await update.message.reply_text(summary, reply_markup=kb)
    return P_CONFIRM

@require_unlock
async def confirm_payment(update: Update, context: Context_TYPES.DEFAULT_TYPE):
    logging.info("confirm_payment: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'pay_yes':
        entry = {
            'customer_id': context.user_data['pay_cust_id'],
            'local_amt':   context.user_data['pay_local_amt'],
            'fee_perc':    context.user_data['pay_fee_perc'],
            'fee_amt':     context.user_data['pay_local_amt'] * context.user_data['pay_fee_perc']/100,
            'usd_amt':     context.user_data['pay_usd_received'],
            'fx_rate':     (context.user_data['pay_local_amt'] - context.user_data['pay_local_amt'] * context.user_data['pay_fee_perc']/100) / context.user_data['pay_usd_received'],
            'inv_rate':    context.user_data['pay_usd_received'] / (context.user_data['pay_local_amt'] - context.user_data['pay_local_amt'] * context.user_data['pay_fee_perc']/100),
            'note':        context.user_data.get('pay_note',''),
            'timestamp':   datetime.utcnow().isoformat()
        }
        secure_db.insert('customer_payments', entry)
        await update.callback_query.edit_message_text(
            f"✅ Payment recorded.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
    else:
        await show_payment_menu(update, context)
    return ConversationHandler.END

# --- View Payments Flow ---
async def view_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("view_payments")
    await update.callback_query.answer()
    rows = secure_db.all('customer_payments')
    if not rows:
        text = "No payments found."
    else:
        text = "Payments:\n"
        cust = Query()
        for r in rows:
            c = secure_db.table('customers').get(doc_id=r['customer_id'])['name']
            text += f"• [{r.doc_id}] {c}: {r['local_amt']:.2f} -> {r['usd_amt']:.2f} USD\n"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✏️ Edit", callback_data="edit_payment"),
        InlineKeyboardButton("🗑️ Remove", callback_data="remove_payment")
    ],[
        InlineKeyboardButton("🔙 Back", callback_data="payment_menu")
    ]])
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
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}=>{r['usd_amt']:.2f}", callback_data=f"edit_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a payment to edit:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_edit_payment_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_edit_payment_selection: %s", update.callback_query.data)
    await update.callback_query.answer()
    parts = update.callback_query.data.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await show_payment_menu(update, context)
    pid = int(parts[1])
    rec = secure_db.table('customer_payments').get(doc_id=pid)
    if not rec:
        return await show_payment_menu(update, context)
    context.user_data['edit_pay'] = rec
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_EDIT_FIELD

async def get_edit_payment_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_edit_payment_field: %s", update.message.text)
    # For simplicity, interpret new value as local_amt, recompute others
    new_local = float(update.message.text.strip())
    rec = context.user_data['edit_pay']
    rec['local_amt'] = new_local
    fee_perc = rec['fee_perc']
    rec['fee_amt'] = new_local * fee_perc/100
    net_local = new_local - rec['fee_amt']
    usd_rec = rec['usd_amt']
    rec['fx_rate'] = net_local / usd_rec
    rec['inv_rate'] = usd_rec / net_local
    secure_db.update('customer_payments', rec, [rec.doc_id])
    await update.message.reply_text(f"✅ Payment updated to {new_local:.2f} {rec['local_amt']:< / user asked too long & cut off */
