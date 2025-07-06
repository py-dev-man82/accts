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
    P_EDIT_NEW,
    P_EDIT_CONFIRM,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM,
) = range(11)

# --- Submenu for Payments ---
async def show_payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payment submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Payment",    callback_data="add_payment")],
            [InlineKeyboardButton("👀 View Payments", callback_data="view_payment")],
            [InlineKeyboardButton("✏️ Edit Payment",  callback_data="edit_payment")],
            [InlineKeyboardButton("🗑️ Remove Payment",callback_data="remove_payment")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])
        await update.callback_query.edit_message_text(
            "Payment Management: choose an action", reply_markup=kb
        )

# --- Add Payment Flow ---
@require_unlock
async def add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_payment")
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Select customer:")
    else:
        await update.message.reply_text("Select customer:")
    # Build customer list
    customers = secure_db.all('customers')
    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"add_pay_{c.doc_id}") for c in customers]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await (update.callback_query or update.message).reply_text(
        "Choose a customer:", reply_markup=kb
    )
    return P_CUST_SELECT

async def get_payment_cust(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_payment_cust: %s", update.callback_query.data)
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[2])
    context.user_data['payment_cust'] = cid
    await update.callback_query.edit_message_text("Enter local currency amount received:")
    return P_LOCAL_AMT

async def get_local_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amt = float(update.message.text.strip())
    context.user_data['payment_local'] = amt
    await update.message.reply_text("Enter handling fee % (e.g. 5 for 5%):")
    return P_FEE_PERC

async def get_fee_perc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    perc = float(update.message.text.strip())
    context.user_data['payment_fee'] = perc
    await update.message.reply_text("Enter USD amount received after conversion:")
    return P_USD_RECEIVED

async def get_usd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usd = float(update.message.text.strip())
    context.user_data['payment_usd'] = usd
    # proceed to optional note
    await update.message.reply_text(
        "Enter an optional note (or send /skip to leave blank):"
    )
    return P_NOTE

async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    if note.lower() == '/skip':
        note = ''
    context.user_data['payment_note'] = note
    # Build summary
    local_amt = context.user_data['payment_local']
    fee_perc = context.user_data['payment_fee']
    fee_amt = local_amt * fee_perc / 100
    net_local = local_amt - fee_amt
    usd_received = context.user_data['payment_usd']
    fx_rate = net_local / usd_received
    inv_rate = usd_received / net_local
    cur = secure_db.table('customers').get(doc_id=context.user_data['payment_cust'])['currency']
    summary = (
        f"Received: {local_amt:.2f} {cur}\n"
        f"Fee: {fee_perc}% ({fee_amt:.2f} {cur})\n"
        f"USD Received: {usd_received:.2f} USD\n\n"
        f"FX Rate: {fx_rate:.4f} {cur}/USD\n"
        f"Inverse: {inv_rate:.4f} USD/{cur}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pay_yes"),
        InlineKeyboardButton("❌ No",  callback_data="pay_no")
    ]])
    await update.message.reply_text(summary, reply_markup=kb)
    return P_CONFIRM

@require_unlock
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_payment: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'pay_yes':
        # Insert record
        secure_db.insert('customer_payments', {
            'customer_id': context.user_data['payment_cust'],
            'local_amt':   context.user_data['payment_local'],
            'fee_perc':    context.user_data['payment_fee'],
            'usd_amt':     context.user_data['payment_usd'],
            'note':        context.user_data.get('payment_note',''),
            'timestamp':   datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            f"✅ Payment recorded.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="payment_menu")
            ]])
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
            c = secure_db.table('customers').get(doc_id=r['customer_id'])['name']
            text += f"• [{r.doc_id}] {c}: {r['local_amt']} -> {r['usd_amt']} USD\n"
        text = "Payments:\n" + "\n".join(lines)
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
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']}=>{r['usd_amt']}", callback_data=f"edit_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select payment to edit:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_payment_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_payment_edit_selection: %s", update.callback_query.data)
    await update.callback_query.answer()
    parts = update.callback_query.data.rsplit("_",1)
    if len(parts)!=2 or not parts[1].isdigit():
        return await show_payment_menu(update, context)
    pid = int(parts[1])
    rec = secure_db.table('customer_payments').get(doc_id=pid)
    if not rec:
        return await show_payment_menu(update, context)
    context.user_data['edit_pay'] = rec
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_EDIT_NEW

async def get_payment_new_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_amt = float(update.message.text.strip())
    context.user_data['edit_new'] = new_amt
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Save", callback_data="pay_edit_yes"),
        InlineKeyboardButton("❌ Cancel", callback_data="pay_edit_no")
    ]])
    await update.message.reply_text(f"Save new amount {new_amt}?", reply_markup=kb)
    return P_EDIT_CONFIRM

@require_unlock
async def confirm_edit_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_edit_payment: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'pay_edit_yes':
        rec = context.user_data['edit_pay']
        secure_db.update('customer_payments', {'local_amt': context.user_data['edit_new']}, [rec.doc_id])
        await update.callback_query.edit_message_text(
            f"✅ Updated payment {rec.doc_id}.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="payment_menu")
            ]])
        )
    else:
        await show_payment_menu(update, context)
    return ConversationHandler.END

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
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']}=>{r['usd_amt']}", callback_data=f"remove_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select payment to delete:", reply_markup=kb)
    return P_DELETE_SELECT

async def get_payment_delete_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_payment_delete_selection: %s", update.callback_query.data)
    await update.callback_query.answer()
    parts = update.callback_query.data.rsplit("_",1)
    if len(parts)!=2 or not parts[1].isdigit():
        return await show_payment_menu(update, context)
    pid = int(parts[1])
    rec = secure_db.table('customer_payments').get(doc_id=pid)
    if not rec:
        return await show_payment_menu(update, context)
    context.user_data['del_pay'] = rec
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, delete", callback_data="pay_del_yes"),
        InlineKeyboardButton("❌ No, cancel",  callback_data="pay_del_no")
    ]])
    await update.callback_query.edit_message_text(
        f"Are you sure you want to delete payment {pid}?", reply_markup=kb
    )
    return P_DELETE_CONFIRM

@require_unlock
async def confirm_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_delete_payment: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'pay_del_yes':
        rec = context.user_data['del_pay']
        secure_db.remove('customer_payments', [rec.doc_id])
        await update.callback_query.edit_message_text(
            f"✅ Payment {rec.doc_id} deleted.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="payment_menu")
            ]])
        )
    else:
        await show_payment_menu(update, context)
    return ConversationHandler.END

# --- Register Handlers ---
def register_payment_handlers(app):
    # Submenu
    app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))

    # Add Flow
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_payment", add_payment),
            CallbackQueryHandler(add_payment, pattern="^add_payment$")
        ],
        states={
            P_CUST_SELECT:   [CallbackQueryHandler(get_payment_cust,    pattern="^add_pay_\d+")],
            P_LOCAL_AMT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_local_amt)],
            P_FEE_PERC:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fee_perc)],
            P_USD_RECEIVED:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_usd_received)],
            P_NOTE:          [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note),
                               CommandHandler("skip", get_payment_note)],
            P_CONFIRM:       [CallbackQueryHandler(confirm_payment, pattern="^pay_" )],
        },
        fallbacks=[CommandHandler("cancel", confirm_payment)],
        per_message=False
    )
    app.add_handler(add_conv)

    # View Flow
    app.add_handler(CallbackQueryHandler(view_payments, pattern="^view_payment$"))

    # Edit Flow
    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_payment", edit_payment),
            CallbackQueryHandler(edit_payment, pattern="^edit_payment$")
        ],
        states={
            P_EDIT_SELECT: [CallbackQueryHandler(get_payment_edit_selection, pattern="^edit_payment_\d+")],
            P_EDIT_NEW:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_new_amt)],
            P_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_payment, pattern="^pay_edit_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_edit_payment)],
        per_message=False
    )
    app.add_handler(edit_conv)

    # Delete Flow
    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("remove_payment", delete_payment),
            CallbackQueryHandler(delete_payment, pattern="^remove_payment$")
        ],
        states={
            P_DELETE_SELECT: [CallbackQueryHandler(get_payment_delete_selection, pattern="^remove_payment_\d+")],
            P_DELETE_CONFIRM:[CallbackQueryHandler(confirm_delete_payment, pattern="^pay_del_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_payment)],
        per_message=False
    )
    app.add_handler(del_conv)
