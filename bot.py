import logging

import config
from secure_db import secure_db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# Import handlers and submenu functions
from handlers.customers import register_customer_handlers, show_customer_menu
from handlers.stores    import register_store_handlers, show_store_menu
from handlers.partners  import register_partner_handlers, show_partner_menu
from handlers.sales     import register_sales_handlers, show_sales_menu
from handlers.payments  import register_payment_handlers, show_payment_menu
from handlers.payouts   import register_payout_handlers, show_payout_menu


def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start or main menu handler: show top-level menu
    """
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Customers",    callback_data="customer_menu")],
        [InlineKeyboardButton("🏪 Stores",        callback_data="store_menu")],
        [InlineKeyboardButton("🤝 Partners",      callback_data="partner_menu")],
        [InlineKeyboardButton("💰 Sales",         callback_data="sales_menu")],
        [InlineKeyboardButton("💵 Payments",      callback_data="payment_menu")],
        [InlineKeyboardButton("💸 Payouts",       callback_data="payout_menu")],
    ])
    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.edit_message_text("Main Menu: choose a section", reply_markup=kb)
    else:
        update.message.reply_text("Main Menu: choose a section", reply_markup=kb)


def main() -> None:
    # Configure logging
    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

    # Build application
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Core handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Register each module
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)

    # Start polling
    app.run_polling()


if __name__ == "__main__":
    main()