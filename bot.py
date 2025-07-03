#!/usr/bin/env python3
import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
)
import config
from secure_db import SecureDB

# Import registration functions from each handlers module
from handlers.customers    import register_customer_handlers
from handlers.stores       import register_store_handlers
from handlers.partners     import register_partner_handlers
from handlers.sales        import register_sales_handlers
from handlers.payments     import register_payment_handlers
from handlers.payouts      import register_payout_handlers
from handlers.stockin      import register_stockin_handlers
from handlers.reports      import register_report_handlers
from handlers.export_excel import register_export_handler

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Initialize encrypted TinyDB ---
secure_db = SecureDB(config.DB_PATH, config.DB_PASSPHRASE)

def start(update, context):
    """Simple /start handler to show main menu."""
    buttons = [
        ["👥 Customers", "manage_customers"],
        ["🏬 Stores",    "manage_stores"],
        ["🤝 Partners",  "manage_partners"],
        ["🛒 Sales",     "manage_sales"],
        ["💰 Payments",  "manage_payments"],
        ["📦 Stock-In",  "manage_stockin"],
        ["📊 Reports",   "manage_reports"],
        ["📁 Export",    "export_excel"],
        ["🔒 Lock",      "lock"]
    ]
    keyboard = [[{"text": text, "callback_data": data}] for text, data in buttons]
    update.message.reply_text("Main Menu:", reply_markup={"inline_keyboard": keyboard})

def unlock_cmd(update, context):
    """Manual unlock if auto-locked."""
    secure_db.unlock()
    update.message.reply_text("🔓 Database unlocked!")

def lock_cmd(update, context):
    """Immediate lock."""
    secure_db.lock()
    update.message.reply_text("🔒 Database locked.")

def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Register core commands
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('unlock', unlock_cmd))
    app.add_handler(CommandHandler('lock',   lock_cmd))

    # Register all feature modules
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    register_stockin_handlers(app)
    register_report_handlers(app)
    register_export_handler(app)

    logger.info("Bot started, polling...")
    app.run_polling()

if __name__ == '__main__':
    main()
