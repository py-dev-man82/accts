#!/usr/bin/env python3
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
    filters
)

# Core utilities
from handlers.utils import require_unlock

# Feature modules already in the project
from handlers.customers         import register_customer_handlers,  show_customer_menu
from handlers.stores            import register_store_handlers,     show_store_menu
from handlers.partners          import register_partner_handlers,   show_partner_menu
from handlers.sales             import register_sales_handlers
from handlers.payments          import register_payment_handlers,   show_payment_menu
from handlers.payouts           import register_payout_handlers,    show_payout_menu
from handlers.stockin           import register_stockin_handlers,   show_stockin_menu
from handlers.partner_sales     import register_partner_sales_handlers, show_partner_sales_menu

# Reports
from handlers.reports.customer_report import register_owner_report_handlers  # 🆕 now comes from customer_report
from handlers.reports.partner_report  import (
    register_partner_report_handlers,
    show_partner_report_menu,
    save_custom_start,
)
from handlers.reports.store_report    import (
    register_store_report_handlers,
    show_store_report_menu,
    save_custom_start as save_custom_start_store,
)

# 🆕  Owner module ––– enabled now
from handlers.owner                  import register_owner_handlers, show_owner_menu

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
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Customers",     callback_data="customer_menu"),
             InlineKeyboardButton("Stores",        callback_data="store_menu")],
            [InlineKeyboardButton("Partners",      callback_data="partner_menu"),
             InlineKeyboardButton("Sales",         callback_data="sales_menu")],
            [InlineKeyboardButton("Payments",      callback_data="payment_menu"),
             InlineKeyboardButton("Payouts",       callback_data="payout_menu")],
            [InlineKeyboardButton("Stock-In",      callback_data="stockin_menu"),
             InlineKeyboardButton("Partner Sales", callback_data="partner_sales_menu")],
            [InlineKeyboardButton("👑 Owner",      callback_data="owner_menu"),
             InlineKeyboardButton("📊 Reports",    callback_data="report_menu")],
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

async def show_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📄 Customer Report", callback_data="rep_cust")],
            [InlineKeyboardButton("📄 Partner Report",  callback_data="rep_part")],
            [InlineKeyboardButton("📄 Store Report",    callback_data="rep_store")],
            [InlineKeyboardButton("📄 Owner Summary",   callback_data="rep_owner")],
            [InlineKeyboardButton("🔙 Back",            callback_data="main_menu")],
        ]
    )
    await update.callback_query.edit_message_text(
        "Reports: choose a type", reply_markup=kb
    )

# ════════════════════════════════════════════════════════════
# Main bot runner
# ════════════════════════════════════════════════════════════
async def run_bot():
    logging.basicConfig(
        format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
        level=logging.INFO,
    )
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Admin commands — put these at the top for highest priority!
    app.add_handler(CommandHandler("restart", restart_bot))
    app.add_handler(CommandHandler("kill",    kill_bot))

    # Root / back
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Reports menu
    app.add_handler(CallbackQueryHandler(show_report_menu, pattern="^report_menu$"))

    # Register all feature handlers
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    register_stockin_handlers(app)
    app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))

    register_partner_sales_handlers(app)
    app.add_handler(
        CallbackQueryHandler(show_partner_sales_menu, pattern="^partner_sales_menu$")
    )

    # Reports
    register_customer_report_handlers(app)  # 🆕 now using customer_report module
    register_partner_report_handlers(app)
    app.add_handler(
        CallbackQueryHandler(show_partner_report_menu, pattern="^rep_part$")
    )
    register_store_report_handlers(app)
    app.add_handler(
        CallbackQueryHandler(show_store_report_menu, pattern="^rep_store$")
    )

    # 🆕 Owner Summary Report (all callbacks wired inside register_owner_report_handlers)
    register_owner_report_handlers(app)

    # 🆕 Owner module registration
    register_owner_handlers(app)
    app.add_handler(
        CallbackQueryHandler(show_owner_menu, pattern="^owner_menu$")
    )

    # --- PATCH: only partner/store need ad-hoc text handlers now ---
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_start_store))

    # Start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    try:
        await asyncio.Event().wait()           # keep process alive
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

# ════════════════════════════════════════════════════════════
# Simple self-supervisor — restarts on crash
# ════════════════════════════════════════════════════
def main_supervisor():
    while True:
        logging.warning("🔄  Starting bot process…")
        exit_code = subprocess.call([sys.executable, __file__, "child"])
        if exit_code == 0:
            logging.warning("✅ Bot exited cleanly.")
            break
        logging.warning(f"⚠️  Bot crashed (exit {exit_code}) — restarting in 5 s …")
        time.sleep(5)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        asyncio.run(run_bot())
    else:
        main_supervisor()
