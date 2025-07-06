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
    P_NOTE,        # optional note
    P_CONFIRM,
    P_EDIT_SELECT,
    P_EDIT_FIELD,
    P_EDIT_VALUE,
    P_EDIT_CONFIRM,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM,
) = range(12)

# --- Submenu for Payments Management ---
async def show_payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payment submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Payment",     callback_data="add_payment")],
            [InlineKeyboardButton("👀 View Payments",  callback_data="view_payments")],
            [InlineKeyboardButton("✏️ Edit Payment",   callback_data="edit_payment")],
            [InlineKeyboardButton("🗑️ Remove Payment",callback_data="remove_payment")],
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
    await update.callback_query.answer()
    # list customers
    rows = secure_db.all('customers')
    if not rows:
        await update.callback_query.edit_message_text(
            "No customers available.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]
            ])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"pay_cust_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return P_CUST_SELECT

async def get_customer_for_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_customer_for_payment: %s", update.callback_query.data)
    await update.callback_query.answer()
    cid = int(update.callback_query.data.rsplit("_",1)[1])
    rec = secure_db.table('customers').get(doc_id=cid)
    if not rec:
        return await show_payment_menu(update, context)
    context.user_data['pay_cust'] = rec
    await update.callback_query.edit_message_text("Enter amount received in local currency:")
    return P_LOCAL_AMT

async def get_local_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    logging.info("Received local amount: %s", text)
    try:
        local_amt = float(text)
    except ValueError:
        await update.message.reply_text("Invalid number. Enter amount received in local currency:")
        return P_LOCAL_AMT
    context.user_data['local_amt'] = local_amt
    await update.message.reply_text("Enter handling fee % (e.g. 5 for 5%):")
    return P_FEE_PERC

async def get_fee_percentage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    logging.info("Received fee percentage: %s", text)
    try:
        fee_perc = float(text)
    except ValueError:
        await update.message.reply_text("Invalid percentage. Enter handling fee %:")
        return P_FEE_PERC
    context.user_data['fee_perc'] = fee_perc
    await update.message.reply_text("Enter USD amount actually received:")
    return P_USD_RECEIVED

async def get_usd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    logging.info("Received USD amount: %s", text)
    try:
        usd_received = float(text)
    except ValueError:
        await update.message.reply_text("Invalid number. Enter USD amount actually received:")
        return P_USD_RECEIVED
    context.user_data['usd_received'] = usd_received
    # compute fee and fx rate
    local_amt = context.user_data['local_amt']
    fee_amt = local_amt * context.user_data['fee_perc'] / 100
    net_local = local_amt - fee_amt
    fx_rate = net_local / usd_received if usd_received else 0
    context.user_data['fee_amt'] = fee_amt
    context.user_data['fx_rate'] = fx_rate
    # prompt for optional note
    await update.message.reply_text(
        "Enter an optional note for this payment (or send /skip to leave blank):"
    )
    return P_NOTE

async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    logging.info("Received note: %s", note)
    if note.lower() == '/skip':
        note = ''
    context.user_data['note'] = note
    # build confirm summary
    rec = context.user_data['pay_cust']
    lines = [
        f"Customer: {rec['name']} ({rec['currency']})",  
        f"Local Received: {context.user_data['local_amt']} {rec['currency']}",
        f"Fee: {context.user_data['fee_perc']}% ({context.user_data['fee_amt']:.2f})",
        f"USD Received: {context.user_data['usd_received']}",
        f"FX Rate: {context.user_data['fx_rate']:.4f}",
        f"Note: {context.user_data['note']}"
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="pay_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="pay_conf_no")]
    ])
    await update.message.reply_text("\n".join(lines), reply_markup=kb)
    return P_CONFIRM

@require_unlock
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_payment: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'pay_conf_yes':
        rec = context.user_data['pay_cust']
        secure_db.insert('customer_payments', {
            'customer_id': rec.doc_id,
            'local_received': context.user_data['local_amt'],
            'fee_perc': context.user_data['fee_perc'],
            'fee_amt': context.user_data['fee_amt'],
            'usd_received': context.user_data['usd_received'],
            'fx_rate': context.user_data['fx_rate'],
            'note': context.user_data.get('note',''),
            'timestamp': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            "✅ Payment recorded.",
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
        text = "No payments recorded."
    else:
        lines = []
        for r in rows:
            cust = secure_db.table('customers').get(doc_id=r['customer_id'])
            lines.append(
                f"[{r.doc_id}] {cust['name']}: {r['local_received']} {cust['currency']} → {r['usd_received']} USD"
            )
        text = "Payments:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# --- (Edit/Delete flows omitted for brevity) ---

# --- Register Handlers ---
def register_payment_handlers(app):
    app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_payment", add_payment),
            CallbackQueryHandler(add_payment, pattern="^add_payment$")
        ],
        states={
            P_CUST_SELECT: [CallbackQueryHandler(get_customer_for_payment, pattern="^pay_cust_")],
            P_LOCAL_AMT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_local_amount)],
            P_FEE_PERC:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fee_percentage)],
            P_USD_RECEIVED:[MessageHandler(filters.TEXT & ~filters.COMMAND, get_usd_received)],
            P_NOTE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note), CommandHandler('skip', get_payment_note)],
            P_CONFIRM:     [CallbackQueryHandler(confirm_payment, pattern="^pay_conf_")],
        },
        fallbacks=[CommandHandler("cancel", confirm_payment)],
        per_message=False
    )
    app.add_handler(add_conv)
    app.add_handler(CallbackQueryHandler(view_payments, pattern="^view_payments$"))
    # Future: register edit_conv, del_conv
