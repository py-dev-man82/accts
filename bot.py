import logging
import asyncio
import os
import sys
import subprocess
import time

import config
from secure_db import secure_db
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from flask import Flask, request

# Core utilities
from handlers.utils import require_unlock

# Feature modules
from handlers.customers import register_customer_handlers
from handlers.stores import register_store_handlers
from handlers.partners import register_partner_handlers
from handlers.sales import register_sales_handlers
from handlers.payments import register_payment_handlers
from handlers.expenses import register_expense_handlers
from handlers.payouts import register_payout_handlers
from handlers.stockin import register_stockin_handlers
from handlers.partner_sales import register_partner_sales_handlers

# Reports
from handlers.reports.customer_report import register_customer_report_handlers
from handlers.reports.partner_report import (
    register_partner_report_handlers,
    show_partner_report_menu,
    save_custom_start,
)
from handlers.reports.store_report import (
    register_store_report_handlers,
    show_store_report_menu,
    save_custom_start as save_custom_start_store,
)
from handlers.reports.owner_report import register_owner_report_handlers

# Owner module
from handlers.owner import register_owner_handlers, show_owner_menu

# Initialize Flask app
app = Flask(__name__)

# ════════════════════════════════════════════════════════════
# Admin-only helper commands
# ════════════════════════════════════════════════════════════
@require_unlock
async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("♻️ Bot is restarting…")
    logging.warning("⚠️  Admin issued /restart — restarting bot.")
    subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0]), "child"])
    raise SystemExit(0)

@require_unlock
async def kill_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛑 Bot is shutting down… it will auto-restart.")
    logging.warning("⚠️  Admin issued /kill — shutting down cleanly.")
    raise SystemExit(0)

# ════════════════════════════════════════════════════════════
# Menus
# ════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Root menu / back-to-root callback."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ADD USER",      callback_data="adduser_menu"),
         InlineKeyboardButton("ADD FINANCIAL", callback_data="addfinancial_menu")],
        [InlineKeyboardButton("👑 Owner",      callback_data="owner_menu"),
         InlineKeyboardButton("📊 Reports",    callback_data="report_menu")],
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

async def show_adduser_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Customers", callback_data="customer_menu")],
        [InlineKeyboardButton("Stores",    callback_data="store_menu")],
        [InlineKeyboardButton("Partners",  callback_data="partner_menu")],
        [InlineKeyboardButton("🔙 Back",   callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text(
        "ADD USER: choose an account type", reply_markup=kb
    )

async def show_addfinancial_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Sales",         callback_data="sales_menu")],
        [InlineKeyboardButton("Payments",      callback_data="payment_menu")],
        [InlineKeyboardButton("Expenses",      callback_data="expense_menu")],
        [InlineKeyboardButton("Payouts",       callback_data="payout_menu")],
        [InlineKeyboardButton("Stock-In",      callback_data="stockin_menu")],
        [InlineKeyboardButton("Partner Sales", callback_data="partner_sales_menu")],
        [InlineKeyboardButton("🔙 Back",       callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text(
        "ADD FINANCIAL: choose a transaction type", reply_markup=kb
    )

async def show_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Customer Report", callback_data="rep_cust")],
        [InlineKeyboardButton("📄 Partner Report",  callback_data="rep_part")],
        [InlineKeyboardButton("📄 Store Report",    callback_data="rep_store")],
        [InlineKeyboardButton("📄 Owner Summary",   callback_data="rep_owner")],
        [InlineKeyboardButton("🔙 Back",            callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text(
        "Reports: choose a type", reply_markup=kb
    )

# ════════════════════════════════════════════════════════════
# Webhook handler
# ════════════════════════════════════════════════════════════
async def process_update(update, application):
    await application.process_update(update)

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.run_coroutine_threadsafe(process_update(update, application), loop)
    return 'OK'

# ════════════════════════════════════════════════════════════
# Main bot runner
# ════════════════════════════════════════════════════════════
async def run_bot():
    global application, loop
    logging.basicConfig(
        format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
        level=logging.INFO,
    )
    application = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Admin commands
    application.add_handler(CommandHandler("restart", restart_bot))
    application.add_handler(CommandHandler("kill",    kill_bot))

    # Root / back
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Add user/financial submenus
    application.add_handler(CallbackQueryHandler(show_adduser_menu,      pattern="^adduser_menu$"))
    application.add_handler(CallbackQueryHandler(show_addfinancial_menu, pattern="^addfinancial_menu$"))

    # Reports menu
    application.add_handler(CallbackQueryHandler(show_report_menu, pattern="^report_menu$"))

    # Register all feature handlers
    register_customer_handlers(application)
    register_store_handlers(application)
    register_partner_handlers(application)
    register_sales_handlers(application)
    register_payment_handlers(application)
    register_expense_handlers(application)
    register_payout_handlers(application)
    register_stockin_handlers(application)
    register_partner_sales_handlers(application)

    # Reports
    register_customer_report_handlers(application)
    register_partner_report_handlers(application)
    application.add_handler(
        CallbackQueryHandler(show_partner_report_menu, pattern="^rep_part$")
    )
    register_store_report_handlers(application)
    application.add_handler(
        CallbackQueryHandler(show_store_report_menu, pattern="^rep_store$")
)
    )
    register_owner_report_handlers(application)

    # Owner module
    register_owner_handlers(application)
    application.add_handler(CallbackQueryHandler(show_owner_menu, pattern="^owner_menu$"))

    # --- PATCH: Add these handlers for custom date input in partner and store reports only
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_start_store))

    # Initialize application
    await application.initialize()
    await application.start()

    # Flask runs in the main thread, so no need to start polling
    return application

# ════════════════════════════════════════════════════════════
# Simple self-supervisor — restarts on crash
# ════════════════════════════════════════════════════════════
def main_supervisor():
    global loop
    while True:
        logging.warning("🔄  Starting bot process…")
        # Create a new event loop for each restart
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Run the bot and Flask app
        try:
            global application
            application = loop.run_until_complete(run_bot())
            app.run(host='0.0.0.0', port=8443, debug=False)
        except SystemExit:
            logging.warning("✅ Bot exited cleanly.")
            break
        except Exception as e:
            logging.warning(f"⚠️  Bot crashed ({str(e)}) — restarting in 5 s …")
            time.sleep(5)
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        main_supervisor()
    else:
        main_supervisor()
