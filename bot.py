# bot.py

import logging
import config
from secure_db import secure_db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Configure root logger
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Import customer submenu and handler registration
from handlers.customers import register_customer_handlers, show_customer_menu

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /start from user %s", update.effective_user.id)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("👤 Customers", callback_data="customer_menu"),
    ]])
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=kb)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Returning to main menu")
    if update.callback_query:
        await update.callback_query.answer()
        try:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("👤 Customers", callback_data="customer_menu"),
            ]])
            await update.callback_query.edit_message_text(
                "Welcome! Choose an option:", reply_markup=kb
            )
        except BadRequest as e:
            # Telegram: “Message is not modified” can be safely ignored
            logger.debug("BadRequest in show_main_menu: %s", e)

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /unlock")
    if not context.args:
        await update.message.reply_text("Usage: /unlock <passphrase>")
        return
    try:
        secure_db.unlock(context.args[0])
        await update.message.reply_text("🔓 Database unlocked.")
    except Exception as e:
        await update.message.reply_text(f"Unlock failed: {e}")
        logger.error("Unlock error: %s", e)

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /lock")
    secure_db.lock()
    await update.message.reply_text("🔒 Database locked.")

def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("lock", lock_command))

    # Main-menu callback
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))

    # Customer flows only
    app.add_handler(CallbackQueryHandler(show_customer_menu, pattern="^customer_menu$"))
    register_customer_handlers(app)

    app.run_polling()

if __name__ == "__main__":
    main()