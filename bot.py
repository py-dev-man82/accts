#!/usr/bin/env python3
import logging
import asyncio
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

from handlers.utils      import require_unlock
from handlers.customers  import register_customer_handlers, show_customer_menu
from handlers.stores     import register_store_handlers, show_store_menu
from handlers.partners   import register_partner_handlers, show_partner_menu
from handlers.sales      import register_sales_handlers
from handlers.payments   import register_payment_handlers, show_payment_menu
from handlers.payouts    import register_payout_handlers, show_payout_menu
# from handlers.stockin    import register_stockin_handlers, show_stockin_menu
# from handlers.reports    import register_report_handlers, show_report_menu
# from handlers.export_excel import register_export_excel_handlers
# from handlers.export_pdf   import register_export_pdf_handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Customers", callback_data="customer_menu"),
         InlineKeyboardButton("Stores",    callback_data="store_menu")],
        [InlineKeyboardButton("Partners",  callback_data="partner_menu"),
         InlineKeyboardButton("Sales",     callback_data="sales_menu")],
        [InlineKeyboardButton("Payments",  callback_data="payment_menu"),
         InlineKeyboardButton("Payouts",   callback_data="payout_menu")],
    ])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Main Menu: choose a section", reply_markup=kb
        )
    else:
        await update.message.reply_text(
            "Main Menu: choose a section", reply_markup=kb
        )

def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # /start command + “Back to main” button
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Section handlers (only up through Payouts enabled)
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    # register_stockin_handlers(app)
    # register_report_handlers(app)
    # register_export_excel_handlers(app)
    # register_export_pdf_handlers(app)

    app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())