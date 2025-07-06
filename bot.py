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

from handlers.customers import register_customer_handlers, show_customer_menu

# --- Main Menu Keyboard Builder ---
def build_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Customers", callback_data="customer_menu")],
        # Other main menu buttons can be added here
    ])

# --- Core Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = build_main_menu()
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=kb)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # CallbackQuery for main menu
    if update.callback_query:
        await update.callback_query.answer()
        kb = build_main_menu()
        try:
            await update.callback_query.edit_message_text(
                "Welcome! Choose an option:", reply_markup=kb
            )
        except BadRequest as e:
            # Ignore 'Message is not modified' errors
            if "Message is not modified" not in str(e):
                raise
    else:
        kb = build_main_menu()
        await update.message.reply_text("Welcome! Choose an option:", reply_markup=kb)

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /unlock <passphrase>")
        return
    try:
        secure_db.unlock(context.args[0])
        await update.message.reply_text("🔓 Database unlocked.")
    except Exception as e:
        await update.message.reply_text(f"Unlock failed: {e}")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secure_db.lock()
    await update.message.reply_text("🔒 Database locked.")

# --- Main Application Entry Point ---
def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("lock", lock_command))

    # Customers flow
    app.add_handler(CallbackQueryHandler(show_customer_menu, pattern="^customer_menu$"))
    register_customer_handlers(app)

    # (Other flows are commented out for isolated testing)
    # app.add_handler(CallbackQueryHandler(show_store_menu, pattern="^store_menu$"))
    # register_store_handlers(app)

    app.run_polling()

if __name__ == "__main__":
    main()
