#!/usr/bin/env python3
import logging
import asyncio
import os
import sys
import subprocess
import time

import config
from secure_db import secure_db, EncryptedJSONStorage
from tinydb import TinyDB
from handlers.ledger import seed_tables
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
)

# Core utilities
from handlers.utils import require_unlock

# States for initdb conversation
CONFIRM_INITDB, ENTER_OLD_PIN, SET_NEW_PIN, CONFIRM_NEW_PIN = range(4)
UNLOCK_PIN = range(1)

# Feature modules
from handlers.customers         import register_customer_handlers,  show_customer_menu
from handlers.stores            import register_store_handlers,     show_store_menu
from handlers.partners          import register_partner_handlers,   show_partner_menu
from handlers.sales             import register_sales_handlers
from handlers.payments          import register_payment_handlers,   show_payment_menu
from handlers.payouts           import register_payout_handlers,    show_payout_menu
from handlers.stockin           import register_stockin_handlers,   show_stockin_menu
from handlers.partner_sales     import register_partner_sales_handlers, show_partner_sales_menu

# Reports
from handlers.reports.customer_report import register_customer_report_handlers
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
from handlers.reports.owner_report    import register_owner_report_handlers

# Owner module
from handlers.owner import register_owner_handlers, show_owner_menu

# ════════════════════════════════════════════════════════════
# Admin-only helper commands
# ════════════════════════════════════════════════════════════
@require_unlock
async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("♻️ Bot is restarting…")
    logging.warning("⚠️ Admin issued /restart — restarting bot.")
    subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0]), "child"])
    raise SystemExit(0)

@require_unlock
async def kill_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛑 Bot is shutting down… it will auto-restart.")
    logging.warning("⚠️ Admin issued /kill — shutting down cleanly.")
    raise SystemExit(0)

# ════════════════════════════════════════════════════════════
# Unlock command flow (with retries + wipe warning)
# ════════════════════════════════════════════════════════════
async def unlock_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔑 *Enter your encryption PIN to unlock:*", parse_mode="Markdown")
    return UNLOCK_PIN

async def unlock_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attempt to unlock the database with provided PIN."""
    pin = update.message.text.strip()
    try:
        secure_db.unlock(pin)
        secure_db.mark_activity()
        await update.message.reply_text("✅ *Database unlocked successfully!*", parse_mode="Markdown")
        return ConversationHandler.END
    except RuntimeError as e:
        # Check if DB was wiped
        if "wiped" in str(e).lower():
            await update.message.reply_text(
                "💣 *Database wiped after too many failed PIN attempts!*",
                parse_mode="Markdown"
            )
            return ConversationHandler.END
        else:
            # Warn and re-prompt
            attempts_left = max(0, 7 - secure_db.failed_attempts)
            warn_msg = (
                f"❌ *Unlock failed:* {e}\n"
                f"⚠️ Attempts left before wipe: {attempts_left}"
            )
            await update.message.reply_text(warn_msg, parse_mode="Markdown")

            # If not wiped, keep prompting
            if attempts_left > 0:
                await update.message.reply_text("🔑 *Try again. Enter your encryption PIN:*", parse_mode="Markdown")
                return UNLOCK_PIN
            else:
                # Already wiped in secure_db
                return ConversationHandler.END

# ════════════════════════════════════════════════════════════
# Auto-lock background task
# ════════════════════════════════════════════════════════════
async def auto_lock_task():
    AUTOLOCK_TIMEOUT = 180
    while True:
        await asyncio.sleep(10)
        if secure_db.is_unlocked():
            now = time.monotonic()
            if now - secure_db.get_last_access() > AUTOLOCK_TIMEOUT:
                secure_db.lock()
                logging.warning("🔒 Auto-lock triggered after inactivity.")

# (InitDB + Menus unchanged)
# ...


# ════════════════════════════════════════════════════════════
# Main Menu
# ════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main menu with DB status indicator."""
    if not os.path.exists(config.DB_PATH):
        status_icon = "📂 No DB found: run /initdb"
    elif secure_db.is_unlocked():
        status_icon = "🔓 Unlocked"
    else:
        status_icon = "🔒 Locked"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ADD USER", callback_data="adduser_menu"),
         InlineKeyboardButton("ADD FINANCIAL", callback_data="addfinancial_menu")],
        [InlineKeyboardButton("👑 Owner", callback_data="owner_menu"),
         InlineKeyboardButton("📊 Reports", callback_data="report_menu")],
    ])

    text = f"Main Menu: choose a section\n\nStatus: *{status_icon}*"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=kb, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=kb, parse_mode="Markdown"
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

    # Admin commands
    app.add_handler(CommandHandler("restart", restart_bot))
    app.add_handler(CommandHandler("kill",    kill_bot))

    # InitDB handler
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("initdb", initdb_start)],
        states={
            CONFIRM_INITDB: [CallbackQueryHandler(initdb_confirm)],
            ENTER_OLD_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_old_pin)],
            SET_NEW_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_pin)],
            CONFIRM_NEW_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_new_pin)],
        },
        fallbacks=[],
    ))

    # Unlock handler
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("unlock", unlock_start)],
        states={UNLOCK_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, unlock_process)]},
        fallbacks=[],
    ))

    # Root / back
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Register feature handlers
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_payout_handlers(app)
    register_stockin_handlers(app)
    register_partner_sales_handlers(app)

    # Reports
    register_customer_report_handlers(app)
    register_partner_report_handlers(app)
    register_store_report_handlers(app)
    register_owner_report_handlers(app)

    # Start polling and background auto-lock
    asyncio.create_task(auto_lock_task())
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

# ════════════════════════════════════════════════════════════
# Self-supervisor
# ════════════════════════════════════════════════════════════
def main_supervisor():
    while True:
        logging.warning("🔄 Starting bot process…")
        exit_code = subprocess.call([sys.executable, __file__, "child"])
        if exit_code == 0:
            logging.warning("✅ Bot exited cleanly.")
            break
        logging.warning(f"⚠️ Bot crashed (exit {exit_code}) — restarting in 5 s …")
        time.sleep(5)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        asyncio.run(run_bot())
    else:
        main_supervisor()
