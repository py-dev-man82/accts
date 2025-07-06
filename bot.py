import logging

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, Update)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)
import config
from secure_db import secure_db

# Import active handlers
from handlers.customers import register_customer_handlers, show_customer_menu
from handlers.stores    import register_store_handlers, show_store_menu
from handlers.partners  import register_partner_handlers, show_partner_menu
from handlers.sales     import register_sales_handlers, show_sales_report
from handlers.payments  import register_payment_handlers, show_payment_menu
from handlers.payouts   import register_payout_handlers, show_payout_menu
# remaining handlers are commented out for now
# from handlers.stockin   import register_stockin_handlers, show_stockin_menu
# from handlers.reports   import register_weekly_handlers
# from handlers.export_excel import register_excel_handlers
# from handlers.export_pdf   import register_pdf_handlers

# --- Main Menu ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Customers",    callback_data="customer_menu")],
        [InlineKeyboardButton("🏬 Stores",       callback_data="store_menu")],
        [InlineKeyboardButton("🤝 Partners",     callback_data="partner_menu")],
        [InlineKeyboardButton("💰 Sales",        callback_data="sales_report")],
        [InlineKeyboardButton("💵 Payments",     callback_data="payment_menu")],
        [InlineKeyboardButton("💳 Payouts",      callback_data="payout_menu")],
        # [InlineKeyboardButton("📦 Stock-In",     callback_data="stockin_menu")],
        # [InlineKeyboardButton("📊 Weekly Rep",   callback_data="weekly_report")],
        # [InlineKeyboardButton("📤 Export XLS",   callback_data="export_excel")],
        # [InlineKeyboardButton("📄 Export PDF",   callback_data="export_pdf")],
    ])
    await update.message.reply_text("Main Menu: choose a section", reply_markup=kb)

# --- Application Setup ---
def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )

    app = ApplicationBuilder()\
        .token(config.BOT_TOKEN)\
        .build()

    # /start and main menu callback
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Register subsystems
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    # register_stockin_handlers(app)
    # register_weekly_handlers(app)
    # register_excel_handlers(app)
    # register_pdf_handlers(app)

    # Launch bot
    app.run_polling()

if __name__ == "__main__":
    main()
