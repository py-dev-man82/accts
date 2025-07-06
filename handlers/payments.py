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
    # Reuse P_LOCAL_AMT, P_FEE_PERC, P_USD_RECEIVED, P_NOTE, P_CONFIRM for edit flow
    P_DELETE_SELECT,
) = range(7)

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
    context.user_data['local_amt'] = float(update.message.text)
    await update.message.reply_text("Enter handling fee % (e.g. 5):")
    return P_FEE_PERC

async def get_fee_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fee_perc'] = float(update.message.text)
    await update.message.reply_text("Enter USD received after conversion:")
    return P_USD_RECEIVED

async def get_usd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['usd_amt'] = float(update.message.text)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Enter note", callback_data="note_yes"),
        InlineKeyboardButton("➖ Skip note",  callback_data="note_skip"),
    ]])
    await update.message.reply_text("Would you like to add an optional note?", reply_markup=kb)
    return P_NOTE

async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Can be called from /skip or button
    note = ''
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.data == 'note_yes':
            await update.callback_query.edit_message_text("Enter note text:")
            return P_NOTE
        # skip
    else:
        text = update.message.text.strip()
        if text.lower() != '/skip':
            note = text
    context.user_data['note'] = note
    # Prepare confirmation summary
    local_amt = context.user_data['local_amt']
    fee_perc = context.user_data['fee_perc']
    fee_amt = local_amt * fee_perc / 100
    net_local = local_amt - fee_amt
    usd_amt = context.user_data['usd_amt']
    fx_rate = net_local / usd_amt if usd_amt else 0
    inv_rate = usd_amt / net_local if net_local else 0
    summary = (
        f"Received: {local_amt:.2f}\n"
        f"Fee: {fee_perc:.2f}% ({fee_amt:.2f})\n"
        f"USD Received: {usd_amt:.2f}\n\n"
        f"FX Rate: {fx_rate:.4f}\n"
        f"Inverse: {inv_rate:.4f}\n"
        f"Note: {note}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pay_conf_yes"),
        InlineKeyboardButton("❌ No",  callback_data="pay_conf_no"),
    ]])
    # reply to correct object
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_CONFIRM

@require_unlock
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'pay_conf_yes':
        local_amt = context.user_data['local_amt']
        fee_perc  = context.user_data['fee_perc']
        rec = {
            'customer_id': context.user_data['customer_id'],
            'local_amt':   local_amt,
            'fee_perc':    fee_perc,
            'fee_amt':     local_amt * fee_perc / 100,
            'usd_amt':     context.user_data['usd_amt'],
            'fx_rate':     (local_amt * (1 - fee_perc/100)) / context.user_data['usd_amt'],
            'note':        context.user_data.get('note',''),
            'timestamp':   datetime.utcnow().isoformat()
        }
        secure_db.insert('customer_payments', rec)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        await update.callback_query.edit_message_text("✅ Payment recorded.", reply_markup=kb)
    else:
        await show_payment_menu(update, context)
    return ConversationHandler.END

# --- View Payments Flow ---
async def view_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View payments")
    await update.callback_query.answer()
    rows = secure_db.all('customer_payments')
    text = ""
    if not rows:
        text = "No payments found."
    else:
        lines = []
        for r in rows:
            cust = secure_db.table('customers').get(doc_id=r['customer_id'])
            name = cust['name'] if cust else 'Unknown'
            lines.append(f"• [{r.doc_id}] {name}: {r.get('local_amt',0):.2f} => {r.get('usd_amt',0):.2f} USD")
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
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        await update.callback_query.edit_message_text("No payments to edit.", reply_markup=kb)
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r.get('local_amt',0):.2f}=>{r.get('usd_amt',0):.2f}", callback_data=f"edit_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a payment to edit:", reply_markup=kb)
    return P_EDIT_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split('_')[-1])
    rec = secure_db.table('customer_payments').get(doc_id=pid)
    if not rec:
        return await show_payment_menu(update, context)
    context.user_data['edit_payment'] = rec
    # preload the existing values for convenience
    context.user_data['local_amt'] = rec.get('local_amt',0)
    context.user_data['fee_perc']  = rec.get('fee_perc',0)
    context.user_data['usd_amt']   = rec.get('usd_amt',0)
    # now prompt for new local
    await update.callback_query.edit_message_text("Enter new amount received (local currency):")
    return P_LOCAL_AMT

# (after this, flow reuses get_local_amount -> get_fee_percent -> get_usd_received -> get_payment_note -> confirm_payment)

# --- Delete Payment Flow ---
@require_unlock
async def delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start delete_payment")
    await update.callback_query.answer()
    rows = secure_db.all('customer_payments')
    if not rows:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        await update.callback_query.edit_message_text("No payments to remove.", reply_markup=kb)
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r.get('local_amt',0):.2f}=>{r.get('usd_amt',0):.2f}", callback_data=f"delete_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a payment to delete:", reply_markup=kb)
    return P_DELETE_SELECT

async def confirm_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split('_')[-1])
    secure_db.remove('customer_payments', [pid])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    await update.callback_query.edit_message_text(f"✅ Payment {pid} deleted.", reply_markup=kb)
    return ConversationHandler.END

# --- Register Handlers ---
def register_payment_handlers(app):
    # submenu
    app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))
    # direct edit/remove menu entries
    app.add_handler(CallbackQueryHandler(edit_payment,   pattern="^edit_payment$"))
    app.add_handler(CallbackQueryHandler(delete_payment, pattern="^remove_payment$"))

    # add flow
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_payment", add_payment),
            CallbackQueryHandler(add_payment, pattern="^add_payment$"),
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
        fallbacks=[CommandHandler("cancel", confirm_payment)],
        per_message=False
    )
    app.add_handler(add_conv)

    # view
    app.add_handler(CallbackQueryHandler(view_payments, pattern="^view_payment$"))

    # edit flow
    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_payment", edit_payment),
            CallbackQueryHandler(edit_payment, pattern="^edit_payment$"),
        ],
        states={
            P_EDIT_SELECT: [CallbackQueryHandler(get_edit_selection, pattern="^edit_payment_")],
            P_LOCAL_AMT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_local_amount)],
            P_FEE_PERC:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fee_percent)],
            P_USD_RECEIVED:[MessageHandler(filters.TEXT & ~filters.COMMAND, get_usd_received)],
            P_NOTE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note),
                             CommandHandler("skip", get_payment_note)],
            P_CONFIRM:     [CallbackQueryHandler(confirm_payment, pattern="^pay_conf_")],
        },
        fallbacks=[CommandHandler("cancel", confirm_payment)],
        per_message=False
    )
    app.add_handler(edit_conv)

    # delete flow
    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("remove_payment", delete_payment),
            CallbackQueryHandler(delete_payment, pattern="^remove_payment$"),
        ],
        states={
            P_DELETE_SELECT: [CallbackQueryHandler(confirm_delete_payment, pattern="^delete_payment_")],
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_payment)],
        per_message=False
    )
    app.add_handler(del_conv)