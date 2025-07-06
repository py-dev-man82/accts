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
    P_CUST_SELECT,        # [add] pick customer to add payment
    P_LOCAL_AMT,
    P_FEE_PERC,
    P_USD_RECEIVED,
    P_NOTE,
    P_CONFIRM,
    P_EDIT_CUST_SELECT,   # [edit] pick customer whose payment to edit
    P_EDIT_SELECT,        # [edit] pick which payment to edit
    P_DELETE_CUST_SELECT, # [delete] pick customer
    P_DELETE_SELECT,      # [delete] pick which payment
) = range(10)

# --- Submenu for Payments ---
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


# --- Add Payment Flow ---
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
    context.user_data['local_amt'] = float(update.message.text)
    await update.message.reply_text("Enter handling fee %:")
    return P_FEE_PERC

async def get_fee_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fee_perc'] = float(update.message.text)
    await update.message.reply_text("Enter USD received:")
    return P_USD_RECEIVED

async def get_usd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['usd_amt'] = float(update.message.text)
    await update.message.reply_text("Enter an optional note (/skip to leave blank):")
    return P_NOTE

async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    note = "" if text.lower() == '/skip' else text
    context.user_data['note'] = note

    # compute summary
    local = context.user_data['local_amt']
    pct   = context.user_data['fee_perc']
    fee   = local * pct/100
    net   = local - fee
    usd   = context.user_data['usd_amt']
    fx    = net/usd
    inv   = usd/net
    summary = (
        f"Received: {local:.2f}\n"
        f"Fee: {pct:.2f}% ({fee:.2f})\n"
        f"USD Recv: {usd:.2f}\n\n"
        f"FX Rate: {fx:.4f}\n"
        f"Inverse: {inv:.4f}\n"
        f"Note: {note or '—'}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pay_conf_yes"),
        InlineKeyboardButton("❌ No",  callback_data="pay_conf_no")
    ]])
    await update.message.reply_text(summary, reply_markup=kb)
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
            'fx_rate':     (context.user_data['local_amt']*(1-context.user_data['fee_perc']/100))
                              /context.user_data['usd_amt'],
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
        text = "No payments."
    else:
        text = "Payments:\n"
        for r in rows:
            cust = secure_db.table('customers').get(doc_id=r['customer_id'])
            name = cust['name'] if cust else "Unknown"
            text += f"• [{r.doc_id}] {name}: {r['local_amt']:.2f} → {r['usd_amt']:.2f} USD\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)


# --- Edit Payment Flow ---
@require_unlock
async def start_edit_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start edit_payment: pick customer")
    await update.callback_query.answer()
    users = secure_db.all('customers')
    buttons = [
        InlineKeyboardButton(u['name'], callback_data=f"edit_user_{u.doc_id}")
        for u in users
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Choose customer:", reply_markup=kb)
    return P_EDIT_CUST_SELECT

async def list_user_payments_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data['edit_customer_id'] = cid
    rows = [r for r in secure_db.all('customer_payments') if r['customer_id']==cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments for this customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(
            f"[{r.doc_id}] {r['local_amt']:.2f}->{r['usd_amt']:.2f}",
            callback_data=f"edit_payment_{r.doc_id}"
        ) for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select payment:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_payment_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    rec = secure_db.table('customer_payments').get(doc_id=pid)
    context.user_data['edit_payment'] = rec
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_LOCAL_AMT


# --- Delete Payment Flow ---
@require_unlock
async def start_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start delete_payment: pick customer")
    await update.callback_query.answer()
    users = secure_db.all('customers')
    buttons = [
        InlineKeyboardButton(u['name'], callback_data=f"del_user_{u.doc_id}")
        for u in users
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Choose customer:", reply_markup=kb)
    return P_DELETE_CUST_SELECT

async def list_user_payments_for_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    rows = [r for r in secure_db.all('customer_payments') if r['customer_id']==cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments for this customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(
            f"[{r.doc_id}] {r['local_amt']:.2f}->{r['usd_amt']:.2f}",
            callback_data=f"delete_payment_{r.doc_id}"
        ) for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
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


# --- Register Handlers ---
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
            P_NOTE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note),
                             CommandHandler("skip", get_payment_note)],
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
            # then reuse the same states as add for amounts & confirm
            P_LOCAL_AMT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_local_amount)],
            P_FEE_PERC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fee_percent)],
            P_USD_RECEIVED: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_usd_received)],
            P_NOTE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note),
                             CommandHandler("skip", get_payment_note)],
            P_CONFIRM:      [CallbackQueryHandler(confirm_payment, pattern="^pay_conf_")],
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