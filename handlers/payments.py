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
    P_USER_SELECT,        # select customer for edit/delete
    P_CUST_SELECT,        # used in add flow
    P_LOCAL_AMT,
    P_FEE_PERC,
    P_USD_RECEIVED,
    P_NOTE,
    P_CONFIRM,
    P_EDIT_CUST_SELECT,   # select customer before edit
    P_EDIT_SELECT,        # select payment to edit
    P_DELETE_CUST_SELECT, # select customer before delete
    P_DELETE_SELECT,      # select payment to delete
) = range(11)


# --- Submenu for Payments ---
async def show_payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payment submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Payment",     callback_data="add_payment")],
            [InlineKeyboardButton("👀 View Payments",   callback_data="view_payment")],
            [InlineKeyboardButton("✏️ Edit Payment",    callback_data="edit_payment")],
            [InlineKeyboardButton("🗑️ Remove Payment",  callback_data="delete_payment")],
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
    buttons = [
        InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"pay_cust_{r.doc_id}")
        for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a customer:", reply_markup=kb)
    return P_CUST_SELECT

# (reuse existing handlers for getting amounts, fee, USD, note, confirm)


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
            text += f"• [{r.doc_id}] {name}: {r.get('local_amt',0):.2f} → {r.get('usd_amt',0):.2f} USD\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)


# --- Edit Payment Flow ---
@require_unlock
async def start_edit_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start edit_payment: choose user")
    await update.callback_query.answer()
    users = secure_db.all('customers')
    buttons = [
        InlineKeyboardButton(u['name'], callback_data=f"edit_user_{u.doc_id}")
        for u in users
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text(
        "Select customer to edit payments:", reply_markup=kb
    )
    return P_EDIT_CUST_SELECT

async def list_user_payments_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data['edit_customer_id'] = cid
    rows = [r for r in secure_db.all('customer_payments') if r['customer_id']==cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments for that customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
        return ConversationHandler.END
    buttons = [
        InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}→{r['usd_amt']:.2f}",
                             callback_data=f"edit_payment_{r.doc_id}")
        for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text(
        "Select payment to edit:", reply_markup=kb
    )
    return P_EDIT_SELECT

# Reuse get_local_amount, get_fee_percent, get_usd_received, get_payment_note
# In confirm_payment, detect context.user_data.get('edit_customer_id') to perform update instead of insert.


# --- Delete Payment Flow ---
@require_unlock
async def start_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start delete_payment: choose user")
    await update.callback_query.answer()
    users = secure_db.all('customers')
    buttons = [
        InlineKeyboardButton(u['name'], callback_data=f"del_user_{u.doc_id}")
        for u in users
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text(
        "Select customer to remove payments:", reply_markup=kb
    )
    return P_DELETE_CUST_SELECT

async def list_user_payments_for_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data['del_customer_id'] = cid
    rows = [r for r in secure_db.all('customer_payments') if r['customer_id']==cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments for that customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
        )
        return ConversationHandler.END
    buttons = [
        InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}→{r['usd_amt']:.2f}",
                             callback_data=f"delete_payment_{r.doc_id}")
        for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text(
        "Select payment to delete:", reply_markup=kb
    )
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

    # Add payment conv (unchanged)
    # ... existing add_conv handler here ...

    app.add_handler(CallbackQueryHandler(view_payments, pattern="^view_payment$"))

    # Edit payment conv
    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_payment", start_edit_payment),
            CallbackQueryHandler(start_edit_payment, pattern="^edit_payment$")
        ],
        states={
            P_EDIT_CUST_SELECT: [CallbackQueryHandler(list_user_payments_for_edit, pattern="^edit_user_")],
            P_EDIT_SELECT:      [CallbackQueryHandler(list_user_payments_for_edit, pattern="^edit_payment_")],
            # then reuse amount & confirm states
        },
        fallbacks=[CommandHandler("cancel", show_payment_menu)],
        per_message=False
    )
    app.add_handler(edit_conv)

    # Delete payment conv
    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("delete_payment", start_delete_payment),
            CallbackQueryHandler(start_delete_payment, pattern="^delete_payment$")
        ],
        states={
            P_DELETE_CUST_SELECT: [CallbackQueryHandler(list_user_payments_for_delete, pattern="^del_user_")],
            P_DELETE_SELECT:      [CallbackQueryHandler(confirm_delete_payment, pattern="^delete_payment_")]
        },
        fallbacks=[CommandHandler("cancel", show_payment_menu)],
        per_message=False
    )
    app.add_handler(del_conv)

