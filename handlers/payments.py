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

# State constants
(
    PAY_SEL_CUST,
    PAY_ASK_LOCAL,
    PAY_ASK_FEE,
    PAY_ASK_USD,
    PAY_CONFIRM,
) = range(5)

def register_payment_handlers(app):
    conv = ConversationHandler(
        entry_points=[CommandHandler('add_payment', start_payment)],
        states={
            PAY_SEL_CUST: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_payment_customer)],
            PAY_ASK_LOCAL: [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_payment_local)],
            PAY_ASK_FEE: [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_payment_fee)],
            PAY_ASK_USD: [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_payment_usd)],
            PAY_CONFIRM: [CallbackQueryHandler(confirm_payment)],
        },
        fallbacks=[CommandHandler('cancel', cancel_payment)],
        allow_reentry=True,
    )
    app.add_handler(conv)

# ... implement start_payment, select_payment_customer, ask_payment_*, confirm_payment, cancel_payment
