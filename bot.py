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

# --- Handler Registrations ---
# Always import your handlers; uncomment registrations as needed
from handlers.customers    import register_customer_handlers, show_customer_menu
from handlers.stores       import register_store_handlers, show_store_menu
from handlers.partners     import register_partner_handlers, show_partner_menu
# from handlers.sales        import register_sales_handlers, show_sales_menu
# from handlers.payments     import register_payment_handlers, show_payment_menu
# from handlers.payouts      import register_payout_handlers, show_payout_menu
# from handlers.stockin      import register_stockin_handlers, show_stockin_menu
# from handlers.reports      import register_report_handlers, show_report_menu
# from handlers.export_excel import register_export_excel, show_export_excel_menu
# from handlers.export_pdf   import register_export_pdf, show_export_pdf_menu

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Core Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /start from %s", update.effective_user.id)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Customers", callback_data="customer_menu"),
            InlineKeyboardButton("🏪 Stores",    callback_data="store_menu"),
        ],
        # Uncomment for additional modules:
        # [InlineKeyboardButton("🤝 Partners", callback_data="partner_menu")],
        # [InlineKeyboardButton("💰 Sales",    callback_data="sales_menu")],
        [InlineKeyboardButton("🔐 Unlock DB", callback_data="unlock_menu")],
    ])
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=kb)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redisplay the main menu"""
    logger.info("Returning to main menu")
    if update.callback_query:
        await update.callback_query.answer()
        try:
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("👤 Customers", callback_data="customer_menu"),
                    InlineKeyboardButton("🏪 Stores",    callback_data="store_menu"),
                ],
            ])
            await update.callback_query.edit_message_text(
                "Welcome! Choose an option:", reply_markup=kb
            )
        except BadRequest as e:
            logger.debug("Main menu not modified: %s", e)

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /unlock <passphrase>"""
    if not context.args:
        await update.message.reply_text("Usage: /unlock <passphrase>")
        return
    try:
        secure_db.unlock(context.args[0])
        await update.message.reply_text("🔓 Database unlocked.")
    except Exception as e:
        logger.error("Unlock failed: %s", e)
        await update.message.reply_text(f"Unlock error: {e}")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /lock"""
    secure_db.lock()
    await update.message.reply_text("🔒 Database locked.")

# --- Main Execution ---
def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("lock", lock_command))
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))

    # Active modules: Customers and Stores
    app.add_handler(CallbackQueryHandler(show_customer_menu, pattern="^customer_menu$"))
    register_customer_handlers(app)
    app.add_handler(CallbackQueryHandler(show_store_menu, pattern="^store_menu$"))
    register_store_handlers(app)

    # Uncomment to activate additional modules:
    # app.add_handler(CallbackQueryHandler(show_partner_menu, pattern="^partner_menu$"))
    register_partner_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_sales_menu, pattern="^sales_menu$"))
    # register_sales_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))
    # register_payment_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_payout_menu, pattern="^payout_menu$"))
    # register_payout_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))
    # register_stockin_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_report_menu, pattern="^report_menu$"))
    # register_report_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_export_excel_menu, pattern="^export_excel_menu$"))
    # register_export_excel(app)
    # app.add_handler(CallbackQueryHandler(show_export_pdf_menu, pattern="^export_pdf_menu$"))
    # register_export_pdf(app)

    app.run_polling()

if __name__ == "__main__":
    main()
