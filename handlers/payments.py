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
            [InlineKeyboardButton("➕ Add Payment", callback_data="add_payment")],
            [InlineKeyboardButton("👀 View Payments", callback_data="view_payment")],
            [InlineKeyboardButton("✏️ Edit Payment", callback_data="edit_payment")],
            [InlineKeyboardButton("🗑️ Remove Payment", callback_data="remove_payment")],
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
    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"pay_cust_{r.doc_id}") for r in rows]
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
    # Prompt for date or skip
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Today", callback_data="skip_date"),
        InlineKeyboardButton("✏️ Enter Date", callback_data="enter_date"),
    ]])
    await update.message.reply_text(
        "Select payment date or skip for today:", reply_markup=kb
    )
    return P_DATE

async def get_payment_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_payment_date: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'skip_date':
        date_str = datetime.utcnow().date().isoformat()
    else:
        # Prompt user to enter specific date
        await update.callback_query.edit_message_text("Enter payment date (YYYY-MM-DD):")
        return P_DATE
    context.user_data['date'] = date_str
    # Advance to note entry
    await update.callback_query.message.reply_text("Enter an optional note (/skip to leave blank):")
    return P_NOTE

async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        note_text = update.callback_query.data
        note = ''
    else:
        note_text = update.message.text.strip()
        note = '' if note_text.lower() == '/skip' else note_text
    context.user_data['note'] = note
    # Calculate summary
    local_amt = context.user_data['local_amt']
    fee_perc = context.user_data['fee_perc']
    fee_amt = local_amt * fee_perc / 100
    usd_amt = context.user_data['usd_amt']
    net_local = local_amt - fee_amt
    fx_rate = net_local / usd_amt if usd_amt else 0
    inv_rate = usd_amt / net_local if net_local else 0
    date_str = context.user_data.get('date', datetime.utcnow().date().isoformat())
    summary = (
        f"Date: {date_str}\n"
        f"Received: {local_amt:.2f}\n"
        f"Fee: {fee_perc:.2f}% ({fee_amt:.2f})\n"
        f"USD Received: {usd_amt:.2f}\n\n"
        f"FX Rate: {fx_rate:.4f}\n"
        f"Inverse FX: {inv_rate:.4f}\n"
        f"Note: {note}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pay_conf_yes"),
        InlineKeyboardButton("❌ No",  callback_data="pay_conf_no"),
    ]])
    if update.callback_query:
        await update.callback_query.message.reply_text(summary, reply_markup=kb)
    else:
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
            'fee_amt':     context.user_data['local_amt'] * context.user_data['fee_perc'] / 100,
            'usd_amt':     context.user_data['usd_amt'],
            'fx_rate':     context.user_data['fx_rate'],
            'note':        context.user_data['note'],
            'date':        context.user_data['date'],
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
            text += (f"• [{r.doc_id}] {name}: {r['local_amt']:.2f} => {r['usd_amt']:.2f} USD ({r['date']})\n")
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
    buttons = [
        InlineKeyboardButton(
            f"[{r.doc_id}] {r['local_amt']:.2f}=>{r['usd_amt']:.2f}",
            callback_data=f"edit_payment_{r.doc_id}"
        ) for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a payment to edit:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.rsplit('_',1)[1])
    rec = secure_db.table('customer_payments').get(doc_id=cid)
    context.user_data['edit_payment'] = rec
    # Pre-fill original values
    context.user_data['local_amt'] = rec['local_amt']
    context.user_data['fee_perc'] = rec['fee_perc']
    context.user_data['usd_amt']  = rec['usd_amt']
    context.user_data['date']     = rec['date']
    context.user_data['note']     = rec.get('note','')
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
    # Prompt date skip/entry
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Today", callback_data="skip_date"),
        InlineKeyboardButton("✏️ Enter Date", callback_data="enter_date"),
    ]])
    await update.message.reply_text("Select new payment date or skip:", reply_markup=kb)
    return P_EDIT_DATE

async def get_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'skip_date':
        date_str = datetime.utcnow().date().isoformat()
    else:
        await update.callback_query.edit_message_text("Enter new payment date (YYYY-MM-DD):")
        return P_EDIT_DATE
    context.user_data['date'] = date_str
    await update.callback_query.message.reply_text("Enter new optional note (/skip to leave blank):")
    return P_EDIT_NOTE

async def get_edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['note'] = '' if text.lower()=='/skip' else text
    # Now confirm update
    rec = context.user_data['edit_payment']
    # recalc rates
    local_amt = context.user_data['local_amt']
    fee_perc = context.user_data['fee_perc']
    fee_amt = local_amt * fee_perc /100
    usd_amt = context.user_data['usd_amt']
    net_local = local_amt - fee_amt
    fx_rate = net_local/usd_amt if usd_amt else 0
    inv_rate= usd_amt/net_local if net_local else 0
    summary = (
        f"Date: {context.user_data['date']}\n"
        f"Received: {local_amt:.2f}\n"
        f"Fee: {fee_perc:.2f}% ({fee_amt:.2f})\n"
        f"USD Received: {usd_amt:.2f}\n\n"
        f"FX Rate: {fx_rate:.4f}\n"
        f"Inverse FX: {inv_rate:.4f}\n"
        f"Note: {context.user_data['note']}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Save", callback_data="edit_conf_yes"),InlineKeyboardButton("❌ Cancel", callback_data="edit_conf_no")]])
    await update.message.reply_text(summary, reply_markup=kb)
    return P_EDIT_CONFIRM

@require_unlock
async def confirm_edit_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data=='edit_conf_yes':
        rec_id = context.user_data['edit_payment'].doc_id
        secure_db.update('customer_payments',{
            'local_amt': context.user_data['local_amt'],
            'fee_perc':  context.user_data['fee_perc'],
            'fee_amt':   context.user_data['local_amt']*context.user_data['fee_perc']/100,
            'usd_amt':   context.user_data['usd_amt'],
            'fx_rate':   (context.user_data['local_amt']*(1-context.user_data['fee_perc']/100))/context.user_data['usd_amt'],
            'date':      context.user_data['date'],
            'note':      context.user_data['note'],
        },[rec_id])
        await update.callback_query.edit_message_text(f"✅ Payment {rec_id} updated.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payment_menu")]]))
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
        await update.callback_query.edit_message_text("No payments to remove.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payment_menu")]]))
        return ConversationHandler.END
    buttons=[InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}=>>{r['usd_amt']:.2f}",callback_data=f"delete_payment_{r.doc_id}") for r in rows]
    kb=InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select a payment to delete:",reply_markup=kb)
    return P_DELETE_SELECT

async def confirm_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did=int(update.callback_query.data.rsplit('_',1)[1])
    secure_db.remove('customer_payments',[did])
    await update.callback_query.edit_message_text(f"✅ Payment {did} deleted.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payment_menu")]]))
    return ConversationHandler.END

# --- Register Handlers ---
def register_payment_handlers(app):
    app.add_handler(CallbackQueryHandler(show_payment_menu,pattern="^payment_menu$"))
    add_conv=ConversationHandler(
        entry_points=[CommandHandler("add_payment",add_payment),CallbackQueryHandler(add_payment,pattern="^add_payment$")],
        states={
            P_CUST_SELECT:   [CallbackQueryHandler(get_payment_customer,pattern="^pay_cust_")],
            P_LOCAL_AMT:     [MessageHandler(filters.TEXT & ~filters.COMMAND,get_local_amount)],
            P_FEE_PERC:      [MessageHandler(filters.TEXT & ~filters.COMMAND,get_fee_percent)],
            P_USD_RECEIVED:  [MessageHandler(filters.TEXT & ~filters.COMMAND,get_usd_received)],
            P_DATE:          [CallbackQueryHandler(get_payment_date,pattern="^(skip_date|enter_date)$"),MessageHandler(filters.TEXT & ~filters.COMMAND,get_payment_date)],
            P_NOTE:          [MessageHandler(filters.TEXT & ~filters.COMMAND,get_payment_note),CommandHandler("skip",get_payment_note)],
            P_CONFIRM:       [CallbackQueryHandler(confirm_payment,pattern="^pay_conf_")],
        },
        fallbacks=[CommandHandler("cancel",confirm_payment)],
        per_message=False
    )
    app.add_handler(add_conv)
    app.add_handler(CallbackQueryHandler(view_payments,pattern="^view_payment$"))
    edit_conv=ConversationHandler(
        entry_points=[CommandHandler("edit_payment",edit_payment),CallbackQueryHandler(edit_payment,pattern="^edit_payment$")],
        states={
            P_EDIT_SELECT: [CallbackQueryHandler(get_edit_selection,pattern="^edit_payment_")],
            P_EDIT_LOCAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_local)],
            P_EDIT_FEE:    [MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_fee)],
            P_EDIT_USD:    [MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_usd)],
            P_EDIT_DATE:   [CallbackQueryHandler(get_edit_date,pattern="^(skip_date|enter_date)$"),MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_date)],
            P_EDIT_NOTE:   [MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_note),CommandHandler("skip",get_edit_note)],
            P_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_payment,pattern="^edit_conf_")],
        },
        fallbacks=[CommandHandler("cancel",confirm_edit_payment)],
        per_message=False
    )
    app.add_handler(edit_conv)
    del_conv=ConversationHandler(
        entry_points=[CommandHandler("delete_payment",delete_payment),CallbackQueryHandler(delete_payment,pattern="^delete_payment$")],
        states={P_DELETE_SELECT:[CallbackQueryHandler(confirm_delete_payment,pattern="^delete_payment_")]},
        fallbacks=[CommandHandler("cancel",confirm_delete_payment)],
        per_message=False
    )
    app.add_handler(del_conv)