# utils.py

import config
from secure_db import secure_db
from telegram import Update
from telegram.ext import ConversationHandler
from functools import wraps

# Decorator to require the DB be unlocked before proceeding
# Skips check entirely if encryption is disabled

def require_unlock(func):
    @wraps(func)
    async def wrapper(update: Update, context):
        # Bypass locking in test mode
        if not getattr(config, 'ENABLE_ENCRYPTION', True):
            return await func(update, context)

        try:
            secure_db.ensure_unlocked()
        except RuntimeError as e:
            # If this was a callback query, answer with an alert
            if hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.answer(str(e), show_alert=True)
            else:
                await update.message.reply_text(str(e))
            return ConversationHandler.END

        return await func(update, context)
    return wrapper
