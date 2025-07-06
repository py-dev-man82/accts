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

# Import customer submenu and handler registration
from handlers.customers import register_customer_handlers, show_customer_menu
# Other flows commented out for isolated testing
# from handlers.stores       import register_store_handlers, show_store_menu
# from handlers.partners     import register_partner_handlers, show_partner_menu
# from handlers.sales        import register_sales_handlers, show_sales_menu
# from handlers.payments     import register_payment_handlers, show_payment_menu
# from handlers.payouts      import register_payout_handlers, show_payout_menu
# from handlers.stockin      import register_stockin_handlers, show_stockin_menu
# from handlers.reports      import register_report_handlers
# from handlers.export_excel import register_export_handler

# --- Core Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Customers", callback_data="customer_menu")],
        # [InlineKeyboardButton("🏪 Stores", callback_data="store_menu")],
        # [InlineKeyboardButton("🤝 Partners", callback_data="partner_menu")],
        # [InlineKeyboardButton("💰 Sales", callback_data="sales_menu")],
        # [InlineKeyboardButton("💵 Payments", callback_data="payment_menu")],
        # [InlineKeyboardButton("📦 Stock-In", callback_data="stockin_menu")],
        # [InlineKeyboardButton("📊 Reports", callback_data="report_menu")],
        # [InlineKeyboardButton("📥 Export", callback_data="export_excel")]
    ])
    await update.message.reply_text("Welcome! Pick an option:", reply_markup=kb)

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /unlock <passphrase>")
        return
    try:
        secure_db.unlock(context.args[0])
        await update.message.reply_text("🔓 Database unlocked.")
        logging.info("DB unlocked successfully")
    except Exception as e:
        await update.message.reply_text(f"Unlock failed: {e}")
        logging.error(f"Unlock error: {e}")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secure_db.lock()
    await update.message.reply_text("🔒 Database locked.")

# --- Main ---
def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("lock", lock_command))

    # Customer submenu and flows
    app.add_handler(CallbackQueryHandler(show_customer_menu, pattern="^customer_menu$"))
    register_customer_handlers(app)

    # Other flows commented out during isolated testing
    # app.add_handler(CallbackQueryHandler(show_store_menu, pattern="^store_menu$"))
    # register_store_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_partner_menu, pattern="^partner_menu$"))
    # register_partner_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_sales_menu, pattern="^sales_menu$"))
    # register_sales_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))
    # register_payment_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_payout_menu, pattern="^payout_menu$"))
    # register_payout_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))
    # register_stockin_handlers(app)
    # register_report_handlers(app)
    # register_export_handler(app)

    app.run_polling()

if __name__ == "__main__":
    main()
