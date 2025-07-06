# handlers/utils.py

import config
from secure_db import secure_db
from telegram import Update
from telegram.ext import ConversationHandler, ContextTypes
from functools import wraps

def require_unlock(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Skip lock‐check entirely in test mode
        if not getattr(config, "ENABLE_ENCRYPTION", True):
            return await func(update, context)

        try:
            secure_db.ensure_unlocked()
        except RuntimeError as e:
            # answer callback queries with an alert, otherwise send a message
            if update.callback_query:
                await update.callback_query.answer(str(e), show_alert=True)
            else:
                await update.message.reply_text(str(e))
            return ConversationHandler.END

        return await func(update, context)
    return wrapper