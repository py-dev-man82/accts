# bot.py

import logging
from config import BOT_TOKEN, ADMIN_TELEGRAM_ID, DB_PATH
from secure_db import secure_db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Import and register your handler modules
from handlers.customers import register_customer_handlers
from handlers.stores    import register_store_handlers
from handlers.partners  import register_partner_handlers
from handlers.sales     import register_sales_handlers
from handlers.payments  import register_payment_handlers
from handlers.payouts   import register_payout_handlers
from handlers.stockin   import register_stockin_handlers
from handlers.reports   import register_report_handlers
from handlers.export_excel import register_export_handler

# --- Lock/Unlock handlers ---

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /unlock <passphrase>")
        return
    passphrase = context.args[0]
    try:
        secure_db.unlock(passphrase)
        await update.message.reply_text("🔓 Database unlocked.")
    except Exception as e:
        await update.message.reply_text(f"Unlock failed: {e}")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secure_db.lock()
    await update.message.reply_text("🔒 Database locked.")

# --- Main ---

def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Lock/Unlock commands
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("lock",   lock_command))

    # Register feature handlers
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    register_stockin_handlers(app)
    register_report_handlers(app)
    register_export_handler(app)

    # Start the bot
    app.run_polling()

if __name__ == "__main__":
    main()