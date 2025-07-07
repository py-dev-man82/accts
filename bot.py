#!/usr/bin/env python3
import logging
import asyncio
import config
from secure_db import secure_db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Existing modules
from handlers.utils           import require_unlock
from handlers.customers       import register_customer_handlers, show_customer_menu
from handlers.stores          import register_store_handlers, show_store_menu
from handlers.partners        import register_partner_handlers, show_partner_menu
from handlers.sales           import register_sales_handlers
from handlers.payments        import register_payment_handlers, show_payment_menu
from handlers.payouts         import register_payout_handlers, show_payout_menu
from handlers.stockin         import register_stockin_handlers, show_stockin_menu

# 🆕 Partner Sales (replacing Reconciliation)
from handlers.partner_sales   import register_partner_sales_handlers, show_partner_sales_menu


# 🆕 Admin-only Kill Command
@require_unlock
async def kill_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🛑 Bot is shutting down… it will restart automatically.")
    else:
        await update.message.reply_text("🛑 Bot is shutting down… it will restart automatically.")
    logging.warning("⚠️ Admin issued /kill — shutting down cleanly.")
    await context.application.stop()
    await context.application.shutdown()
    raise SystemExit(0)


# 🆕 Confirm shutdown from button
async def confirm_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, shut down", callback_data="kill_confirm_yes"),
         InlineKeyboardButton("❌ Cancel",         callback_data="main_menu")]
    ])
    await update.callback_query.edit_message_text(
        "⚠️ Are you sure you want to kill the bot?\nIt will restart automatically.",
        reply_markup=kb
    )


async def handle_kill_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "kill_confirm_yes":
        await kill_bot(update, context)
    else:
        # Back to main menu
        await start(update, context)


# 🏠 Main Menu
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Customers",        callback_data="customer_menu"),
         InlineKeyboardButton("Stores",           callback_data="store_menu")],
        [InlineKeyboardButton("Partners",         callback_data="partner_menu"),
         InlineKeyboardButton("Sales",            callback_data="sales_menu")],
        [InlineKeyboardButton("Payments",         callback_data="payment_menu"),
         InlineKeyboardButton("Payouts",          callback_data="payout_menu")],
        [InlineKeyboardButton("Stock-In",         callback_data="stockin_menu"),
         InlineKeyboardButton("Partner Sales",    callback_data="partner_sales_menu")],
        [InlineKeyboardButton("🛑 Kill Bot",       callback_data="kill_bot")],  # 🆕 Kill button
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


# 🔥 Bot setup
def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Main menu + back button
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Register handlers
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    register_stockin_handlers(app)
    app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))

    # Partner Sales replaces Reconciliation
    register_partner_sales_handlers(app)
    app.add_handler(CallbackQueryHandler(show_partner_sales_menu, pattern="^partner_sales_menu$"))

    # 🆕 Kill command handlers
    app.add_handler(CommandHandler("kill", kill_bot))  # /kill command
    app.add_handler(CallbackQueryHandler(confirm_kill,      pattern="^kill_bot$"))          # Kill button
    app.add_handler(CallbackQueryHandler(handle_kill_confirm, pattern="^kill_confirm_"))    # Yes/Cancel confirm

    app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
