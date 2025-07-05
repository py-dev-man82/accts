# bot.py

import logging
import config
from secure_db import secure_db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
)
from functools import wraps

# Import and register your handler modules:
from handlers.customers     import register_customer_handlers
from handlers.stores        import register_store_handlers
from handlers.partners      import register_partner_handlers
from handlers.sales         import register_sales_handlers
from handlers.payments      import register_payment_handlers
from handlers.payouts       import register_payout_handlers
from handlers.stockin       import register_stockin_handlers
from handlers.reports       import register_report_handlers
from handlers.export_excel  import register_export_handler

# Decorator to require DB unlocked (skipped when encryption disabled)
def require_unlock(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not config.ENABLE_ENCRYPTION:
            return await func(update, context)

        try:
            secure_db.ensure_unlocked()
        except RuntimeError as e:
            if update.callback_query:
                await update.callback_query.answer(str(e), show_alert=True)
            else:
                await update.message.reply_text(str(e))
            return ConversationHandler.END

        return await func(update, context)
    return wrapper

# --- Core command handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Customers", callback_data="add_customer"),
         InlineKeyboardButton("🏪 Stores",    callback_data="add_store")],
        [InlineKeyboardButton("🤝 Partners", callback_data="add_partner"),
         InlineKeyboardButton("💰 Sales",    callback_data="add_sale")],
        [InlineKeyboardButton("💵 Payments", callback_data="add_payment"),
         InlineKeyboardButton("📦 Stock-In", callback_data="add_stockin")],
        [InlineKeyboardButton("📊 Reports",  callback_data="rep_owner"),
         InlineKeyboardButton("📥 Export",   callback_data="export_excel")]
    ])
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=kb)

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /unlock <passphrase>")
        return
    try:
        secure_db.unlock(context.args[0])
        await update.message.reply_text("🔓 Database unlocked.")
        logging.info("DB unlocked")
    except Exception as e:
        await update.message.reply_text(f"Unlock failed: {e}")
        logging.error(f"Unlock error: {e}")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secure_db.lock()
    await update.message.reply_text("🔒 Database locked.")

def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Register core commands first
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("lock",   lock_command))

    # Then register all your feature flows
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    register_stockin_handlers(app)
    register_report_handlers(app)
    register_export_handler(app)

    app.run_polling()

if __name__ == "__main__":
    main()