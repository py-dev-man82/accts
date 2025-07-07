# handlers/utils.py

import config
from secure_db import secure_db
from telegram import Update
from telegram.ext import ConversationHandler, ContextTypes
from functools import wraps

def require_unlock(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # If encryption is off, skip the lock check entirely
        if not getattr(config, "ENABLE_ENCRYPTION", True):
            return await func(update, context)

        try:
            secure_db.ensure_unlocked()
        except RuntimeError as e:
            # answer callback queries with an alert, or send a message
            if update.callback_query:
                await update.callback_query.answer(str(e), show_alert=True)
            else:
                await update.message.reply_text(str(e))
            return ConversationHandler.END

        return await func(update, context)
    return wrapper
    # ───────────────────────────────────────────────────────────────
#  Formatting helpers – money  &  date
# ───────────────────────────────────────────────────────────────
from datetime import datetime

# ── Money ──────────────────────────────────────────────────────
_CURRENCY_SIGNS = {
    "USD": "$",  "AUD": "A$", "CAD": "C$",
    "EUR": "€",  "GBP": "£",  "JPY": "¥",
    # add or override as needed …
}

def fmt_money(amount: float, code: str | None = "USD") -> str:
    """
    1234567.8, 'USD' → '$1,234,567.80'
    Unknown codes fall back to '<CODE> 1,234,567.80'
    """
    sign = _CURRENCY_SIGNS.get((code or "USD").upper(), f"{code or ''} ")
    return f"{sign}{amount:,.2f}"

# ── Date ───────────────────────────────────────────────────────
def fmt_date(ddmmyyyy: str | None) -> str:
    """
    '15062025' → '15/06/2025'.
    If parsing fails, return the original string unchanged.
    """
    if not ddmmyyyy:
        return ""
    try:
        return datetime.strptime(ddmmyyyy, "%d%m%Y").strftime("%d/%m/%Y")
    except ValueError:
        return ddmmyyyy