# handlers/payouts.py

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
(PO_PART, PO_USD, PO_CONFIRM) = range(3)

def register_payout_handlers(app):
    conv = ConversationHandler(
        entry_points=[CommandHandler('add_payout', start_payout)],
        states={
            PO_PART: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_payout_partner)],
            PO_USD: [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_payout_usd)],
            PO_CONFIRM: [CallbackQueryHandler(confirm_payout)],
        },
        fallbacks=[CommandHandler('cancel', cancel_payout)],
        allow_reentry=True,
    )
    app.add_handler(conv)

# ... implement start_payout, select_payout_partner, ask_payout_usd, confirm_payout, cancel_payout
