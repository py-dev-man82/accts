# handlers/stockin.py

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
    SI_PART,
    SI_ITEM,
    SI_QTY,
    SI_COST,
    SI_CONFIRM,
) = range(5)

def register_stockin_handlers(app):
    conv = ConversationHandler(
        entry_points=[CommandHandler('add_stockin', start_stockin)],
        states={
            SI_PART: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_stockin_partner)],
            SI_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_stockin_item)],
            SI_QTY: [MessageHandler(filters.Regex(r'^\d+$'), ask_stockin_qty)],
            SI_COST: [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_stockin_cost)],
            SI_CONFIRM: [CallbackQueryHandler(confirm_stockin)],
        },
        fallbacks=[CommandHandler('cancel', cancel_stockin)],
        allow_reentry=True,
    )
    app.add_handler(conv)

# ... implement start_stockin, select_stockin_*, ask_stockin_*, confirm_stockin, cancel_stockin
