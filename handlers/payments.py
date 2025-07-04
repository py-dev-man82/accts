# handlers/payments.py

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
from secure_db import secure_db

# State constants for Payment flow
(
    PAY_SEL_CUST,
    PAY_ASK_LOCAL,
    PAY_ASK_FEE,
    PAY_ASK_USD,
    PAY_CONFIRM,
) = range(5)

# Register payment handlers
def register_payment_handlers(app):
    payment_conv = ConversationHandler(
        entry_points=[CommandHandler('add_payment', start_payment)],
        states={
            PAY_SEL_CUST: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_payment_customer)],
            PAY_ASK_LOCAL: [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_payment_local)],
            PAY_ASK_FEE:   [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_payment_fee)],
            PAY_ASK_USD:   [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_payment_usd)],
            PAY_CONFIRM:   [CallbackQueryHandler(confirm_payment, pattern='^(pay_confirm|pay_cancel)$')],
        },
        fallbacks=[CommandHandler('cancel', cancel_payment)],
        allow_reentry=True,
    )
    app.add_handler(payment_conv)

# --- Payment flow handlers ---
async def start_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter customer ID for payment:")
    return PAY_SEL_CUST

async def select_payment_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cust = update.message.text.strip()
    context.user_data['pay_customer'] = cust
    await update.message.reply_text("Enter amount received (local currency):")
    return PAY_ASK_LOCAL

async def ask_payment_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    local_amt = float(update.message.text.strip())
    context.user_data['pay_local'] = local_amt
    await update.message.reply_text("Enter handling fee (local currency):")
    return PAY_ASK_FEE

async def ask_payment_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fee = float(update.message.text.strip())
    context.user_data['pay_fee'] = fee
    # Calculate USD amount after fee? Ask user:
    await update.message.reply_text("Enter USD amount received: ")
    return PAY_ASK_USD

async def ask_payment_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usd_amt = float(update.message.text.strip())
    context.user_data['pay_usd'] = usd_amt
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data='pay_confirm'),
        InlineKeyboardButton("❌ Cancel",  callback_data='pay_cancel')
    ]])
    summary = (
        f"Payment summary:\n"
        f"Customer: {context.user_data['pay_customer']}\n"
        f"Local:    {context.user_data['pay_local']:.2f}\n"
        f"Fee:      {context.user_data['pay_fee']:.2f}\n"
        f"USD:      {context.user_data['pay_usd']:.2f}"
    )
    await update.message.reply_text(summary, reply_markup=kb)
    return PAY_CONFIRM

async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == 'pay_confirm':
        secure_db.insert('customer_payments', {
            'customer_id': context.user_data['pay_customer'],
            'local_amount': context.user_data['pay_local'],
            'fee':          context.user_data['pay_fee'],
            'usd_amount':   context.user_data['pay_usd'],
            'created_at':   datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text("✅ Payment recorded.")
    else:
        await update.callback_query.edit_message_text("❌ Payment cancelled.")
    return ConversationHandler.END

async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Payment entry cancelled.")
    return ConversationHandler.END
