#!/usr/bin/env python3
import asyncio
import logging

import config
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# Section handlers
from handlers.customers  import register_customer_handlers
from handlers.stores     import register_store_handlers
from handlers.partners   import register_partner_handlers
from handlers.sales      import register_sales_handlers
from handlers.payments   import register_payment_handlers
from handlers.payouts    import register_payout_handlers
from handlers.stockin    import register_stockin_handlers
from handlers.owner      import register_owner_handlers

# ─────────────────────────────────────────────
# Main-menu callback
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the root menu or refresh it when “🔙 Back” is pressed."""
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Customers", callback_data="customer_menu"),
             InlineKeyboardButton("Stores",    callback_data="store_menu")],

            [InlineKeyboardButton("Partners",  callback_data="partner_menu"),
             InlineKeyboardButton("Sales",     callback_data="sales_menu")],

            [InlineKeyboardButton("Payments",  callback_data="payment_menu"),
             InlineKeyboardButton("Payouts",   callback_data="payout_menu")],

            [InlineKeyboardButton("Stock-In",  callback_data="stockin_menu"),
             InlineKeyboardButton("👑 Owner",  callback_data="owner_menu")],
        ]
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Main Menu: choose a section", reply_markup=kb
        )
    else:
        await update.message.reply_text(
            "Main Menu: choose a section", reply_markup=kb
        )

# ─────────────────────────────────────────────
# Entry-point
# ─────────────────────────────────────────────
def main():
    logging.basicConfig(
        format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
        level=logging.INFO,
    )

    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # /start command + “Back to main”
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Register feature modules
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    register_stockin_handlers(app)   # ← ENABLED
    register_owner_handlers(app)

    app.run_polling()

# ─────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(main())