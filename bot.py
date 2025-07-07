# bot.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import logging

# Import handlers
from handlers.customers import register_customer_handlers
from handlers.stores import register_store_handlers
from handlers.partners import register_partner_handlers
from handlers.sales import register_sales_handlers
from handlers.payments import register_payment_handlers
from handlers.payouts import register_payout_handlers
from handlers.stockin import register_stockin_handlers

# 🚨 Import customer report
from handlers.reports.customer_report import register_customer_report_handlers

# ────────────────────────────────────────────────────────────
#  Main Menu
# ────────────────────────────────────────────────────────────
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Customers", callback_data="customer_menu"),
         InlineKeyboardButton("🏬 Stores",    callback_data="store_menu")],
        [InlineKeyboardButton("🤝 Partners",  callback_data="partner_menu"),
         InlineKeyboardButton("🛒 Sales",     callback_data="sales_menu")],
        [InlineKeyboardButton("💵 Payments",  callback_data="payment_menu"),
         InlineKeyboardButton("🏦 Payouts",   callback_data="payout_menu")],
        [InlineKeyboardButton("📦 Stock-In",  callback_data="stockin_menu")],
        [InlineKeyboardButton("📊 Reports",   callback_data="report_menu")],
    ])
    await update.callback_query.edit_message_text("Main Menu: choose a section", reply_markup=kb)


# ────────────────────────────────────────────────────────────
#  Reports Menu
# ────────────────────────────────────────────────────────────
async def show_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Customer Report", callback_data="rep_cust")],
        # Placeholders for future
        [InlineKeyboardButton("📄 Partner Report",  callback_data="rep_part")],
        [InlineKeyboardButton("📄 Store Report",    callback_data="rep_store")],
        [InlineKeyboardButton("📄 Owner Summary",   callback_data="rep_owner")],
        [InlineKeyboardButton("🔙 Back",            callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text("Reports: choose a type", reply_markup=kb)


# ────────────────────────────────────────────────────────────
#  Main Bot Setup
# ────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token("YOUR_TELEGRAM_BOT_TOKEN").build()

    # Main menu handler
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(CommandHandler("start", main_menu))

    # Reports menu handler
    app.add_handler(CallbackQueryHandler(show_report_menu, pattern="^report_menu$"))

    # Register other handlers
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    register_stockin_handlers(app)

    # 🚨 Register customer report handlers
    register_customer_report_handlers(app)

    app.run_polling()


if __name__ == "__main__":
    main()