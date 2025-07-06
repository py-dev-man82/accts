# bot.py

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# --- Handlers ---
from handlers.customers import register_customer_handlers
from handlers.stores import register_store_handlers

# Uncomment these when ready to add more handlers
# from handlers.partners import register_partner_handlers
# from handlers.sales import register_sales_handlers
# from handlers.payments import register_payment_handlers
# from handlers.payouts import register_payout_handlers
# from handlers.stockin import register_stockin_handlers
# from handlers.reports import register_reports_handlers

# --- Logging Setup ---
import logging

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Start Command ---
async def start(update: Update, context):
    """Starts the conversation."""
    user = update.effective_user
    await update.message.reply_text(f"Hello {user.first_name}! Use the menu to manage your data.")

# --- Main Setup ---
def main():
    """Main function to run the bot."""
    app = Application.builder().token('YOUR_BOT_TOKEN').build()

    # --- Register Handlers ---
    register_customer_handlers(app)
    register_store_handlers(app)
    
    # Uncomment these when ready
    # register_partner_handlers(app)
    # register_sales_handlers(app)
    # register_payment_handlers(app)
    # register_payout_handlers(app)
    # register_stockin_handlers(app)
    # register_reports_handlers(app)

    app.add_handler(CommandHandler("start", start))

    app.run_polling()

if __name__ == "__main__":
    main()