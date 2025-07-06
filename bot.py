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

# Import submenu display functions and handler registrations
from handlers.customers import register_customer_handlers, show_customer_menu
from handlers.stores    import register_store_handlers,    show_store_menu
from handlers.partners  import register_partner_handlers,  show_partner_menu
from handlers.sales     import register_sales_handlers,   show_sales_menu

# Uncomment additional handlers as they become active
from handlers.payments     import register_payment_handlers,   show_payment_menu
# from handlers.payouts      import register_payout_handlers,    show_payout_menu
# from handlers.stockin      import register_stockin_handlers,  show_stockin_menu
# from handlers.reports      import register_reports_handlers,  show_report_menu
# from handlers.export_pdf   import register_export_pdf
# from handlers.export_excel import register_export_excel

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("User %s issued /start", update.effective_user.id)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Customers", callback_data="customer_menu"),
            InlineKeyboardButton("🏪 Stores",    callback_data="store_menu"),
            InlineKeyboardButton("🤝 Partners",  callback_data="partner_menu"),
        ],
        [
            InlineKeyboardButton("💰 Sales", callback_data="sales_menu"),
        ]
    ])
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=kb)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        try:
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("👤 Customers", callback_data="customer_menu"),
                    InlineKeyboardButton("🏪 Stores",    callback_data="store_menu"),
                    InlineKeyboardButton("🤝 Partners",  callback_data="partner_menu"),
                ],
                [
                    InlineKeyboardButton("💰 Sales", callback_data="sales_menu"),
                ]
            ])
            await update.callback_query.edit_message_text(
                "Welcome! Choose an option:", reply_markup=kb
            )
        except BadRequest:
            # ignore "message not modified"
            pass

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("User %s requested unlock", update.effective_user.id)
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
    logger.info("User %s requested lock", update.effective_user.id)
    secure_db.lock()
    await update.message.reply_text("🔒 Database locked.")


def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu$"))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("lock",   lock_command))

    # Customer flows
    app.add_handler(CallbackQueryHandler(show_customer_menu, pattern="^customer_menu$"))
    register_customer_handlers(app)

    # Store flows
    app.add_handler(CallbackQueryHandler(show_store_menu, pattern="^store_menu$"))
    register_store_handlers(app)

    # Partner flows
    app.add_handler(CallbackQueryHandler(show_partner_menu, pattern="^partner_menu$"))
    register_partner_handlers(app)

    # Sales flows
    app.add_handler(CallbackQueryHandler(show_sales_menu, pattern="^sales_menu$"))
    register_sales_handlers(app)

    # Uncomment when ready:
    # app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))
    register_payment_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_payout_menu, pattern="^payout_menu$"))
    # register_payout_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))
    # register_stockin_handlers(app)
    # app.add_handler(CallbackQueryHandler(show_report_menu, pattern="^report_menu$"))
    # register_reports_handlers(app)
    # register_export_pdf(app)
    # register_export_excel(app)

    app.run_polling()


if __name__ == "__main__":
    main()
