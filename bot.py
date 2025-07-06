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

# --- Handler Registrations ---
# Customers
from handlers.customers import register_customer_handlers, show_customer_menu
# Stores
from handlers.stores    import register_store_handlers, show_store_menu
# Partners
from handlers.partners  import register_partner_handlers, show_partner_menu
# Sales
from handlers.sales     import register_sales_handlers, show_sales_menu
# Payments
from handlers.payments  import register_payment_handlers, show_payment_menu
# Payouts
from handlers.payouts   import register_payout_handlers, show_payout_menu

# Uncomment when ready:
# # Stock-In
# from handlers.stockin   import register_stockin_handlers, show_stockin_menu
# # Reports
# from handlers.reports   import register_report_handlers, show_report_menu
# # Export Excel
# from handlers.export_excel import register_export_excel_handlers
# # Export PDF
# from handlers.export_pdf import register_export_pdf_handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Customers", callback_data="customer_menu")],
        [InlineKeyboardButton("🏬 Stores",    callback_data="store_menu")],
        [InlineKeyboardButton("🤝 Partners",  callback_data="partner_menu")],
        [InlineKeyboardButton("💰 Sales",     callback_data="sales_menu")],
        [InlineKeyboardButton("💵 Payments",  callback_data="payment_menu")],
        [InlineKeyboardButton("📤 Payouts",   callback_data="payout_menu")],
        # [InlineKeyboardButton("📦 Stock-In",  callback_data="stockin_menu")],
        # [InlineKeyboardButton("📄 Reports",   callback_data="report_menu")],
        # [InlineKeyboardButton("📊 Export Excel", callback_data="export_excel")],
        # [InlineKeyboardButton("📑 Export PDF",   callback_data="export_pdf")],
    ])
    await update.message.reply_text("Main Menu: choose a section", reply_markup=kb)

async def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # /start handler
    app.add_handler(CommandHandler("start", start))

    # Register menus
    app.add_handler(CallbackQueryHandler(show_customer_menu, pattern="^customer_menu$"))
    app.add_handler(CallbackQueryHandler(show_store_menu,    pattern="^store_menu$"))
    app.add_handler(CallbackQueryHandler(show_partner_menu,  pattern="^partner_menu$"))
    app.add_handler(CallbackQueryHandler(show_sales_menu,    pattern="^sales_menu$"))
    app.add_handler(CallbackQueryHandler(show_payment_menu,  pattern="^payment_menu$"))
    app.add_handler(CallbackQueryHandler(show_payout_menu,   pattern="^payout_menu$"))

    # Register each feature's handlers
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

    # Start polling
    await app.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
