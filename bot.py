# bot.py

import logging
import config
from secure_db import secure_db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Import submenu display functions and register functions
from handlers.customers import register_customer_handlers, show_customer_menu
from handlers.stores    import register_store_handlers, show_store_menu
from handlers.partners  import register_partner_handlers, show_partner_menu
from handlers.sales     import register_sales_handlers, show_sales_menu
from handlers.payments  import register_payment_handlers, show_payments_menu
from handlers.payouts   import register_payout_handlers, show_payouts_menu
from handlers.stockin   import register_stockin_handlers, show_stockin_menu
from handlers.reports   import register_report_handlers, show_reports_menu
from handlers.export_excel import register_export_handler, show_export_menu

# --- Core command handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Main menu
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Customers",    callback_data="customer_menu"),
         InlineKeyboardButton("🏪 Stores",       callback_data="store_menu")],
        [InlineKeyboardButton("🤝 Partners",     callback_data="partner_menu"),
         InlineKeyboardButton("💰 Sales",        callback_data="sales_menu")],
        [InlineKeyboardButton("💵 Payments",     callback_data="payments_menu"),
         InlineKeyboardButton("📦 Stock-In",     callback_data="stockin_menu")],
        [InlineKeyboardButton("📊 Reports",      callback_data="reports_menu"),
         InlineKeyboardButton("📥 Export Excel", callback_data="export_menu")]
    ])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Welcome! Pick an option:", reply_markup=kb
        )
    else:
        await update.message.reply_text(
            "Welcome! Pick an option:", reply_markup=kb
        )

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /unlock <passphrase>")
        return
    passphrase = context.args[0]
    try:
        secure_db.unlock(passphrase)
        await update.message.reply_text("🔓 Database unlocked.")
        logging.info("DB unlocked successfully")
    except Exception as e:
        await update.message.reply_text(f"❌ Unlock failed: {e}")
        logging.error(f"Unlock error: {e}")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secure_db.lock()
    await update.message.reply_text("🔒 Database locked.")

# --- Main ---
def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("unlock",  unlock_command))
    app.add_handler(CommandHandler("lock",    lock_command))
    # Back to main menu shortcut
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Submenu callbacks
    app.add_handler(CallbackQueryHandler(show_customer_menu, pattern="^customer_menu$"))
    app.add_handler(CallbackQueryHandler(show_store_menu,    pattern="^store_menu$"))
    app.add_handler(CallbackQueryHandler(show_partner_menu,  pattern="^partner_menu$"))
    app.add_handler(CallbackQueryHandler(show_sales_menu,    pattern="^sales_menu$"))
    app.add_handler(CallbackQueryHandler(show_payments_menu, pattern="^payments_menu$"))
    app.add_handler(CallbackQueryHandler(show_payouts_menu,  pattern="^payouts_menu$"))
    app.add_handler(CallbackQueryHandler(show_stockin_menu,  pattern="^stockin_menu$"))
    app.add_handler(CallbackQueryHandler(show_reports_menu,  pattern="^reports_menu$"))
    app.add_handler(CallbackQueryHandler(show_export_menu,   pattern="^export_menu$"))

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

    # Start polling
    app.run_polling()

if __name__ == "__main__":
    main()
