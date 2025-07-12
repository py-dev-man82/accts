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
    filters,
    ConversationHandler,
)

# Core utilities
from handlers.utils import require_unlock

# States for initdb conversations
CONFIRM_INITDB, PASSWORD_INITDB = range(2)
CONFIRM_INITDB2 = range(1)

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
async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("♻️ Bot is restarting…")
    logging.warning("⚠️ Admin issued /restart — restarting bot.")
    subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0]), "child"])
    raise SystemExit(0)

async def kill_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛑 Bot is shutting down… it will auto-restart.")
    logging.warning("⚠️ Admin issued /kill — shutting down cleanly.")
    raise SystemExit(0)

# ════════════════════════════════════════════════════════════
# Secure InitDB flow (requires PIN)
# ════════════════════════════════════════════════════════════
async def initdb_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for confirmation before resetting DB."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="initdb_yes"),
         InlineKeyboardButton("❌ No",  callback_data="initdb_no")]
    ])
    await update.message.reply_text(
        "⚠️ *WARNING: This will DELETE all data and create a fresh database.*\n\n"
        "Are you sure you want to proceed?",
        parse_mode="Markdown", reply_markup=kb)
    return CONFIRM_INITDB

async def initdb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "initdb_no":
        await update.callback_query.edit_message_text("❌ InitDB cancelled.")
        return ConversationHandler.END

    await update.callback_query.edit_message_text("🔑 Enter database PIN to confirm:")
    return PASSWORD_INITDB

async def initdb_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check PIN and reset DB."""
    pin = update.message.text.strip()
    try:
        secure_db.unlock(pin)  # Try to unlock with provided PIN
        db_path = config.DB_PATH

        # Wipe DB file
        if os.path.exists(db_path):
            os.remove(db_path)
            logging.warning(f"⚠️ Database file {db_path} deleted.")

        # Recreate DB (encrypted if ENABLE_ENCRYPTION is True)
        secure_db.unlock(pin)
        secure_db.lock()

        await update.message.reply_text(
            "✅ Database reset successfully.\nYou can now /unlock to start fresh."
        )
    except Exception as e:
        logging.error(f"InitDB failed: {e}")
        await update.message.reply_text(
            f"❌ Wrong PIN or error resetting DB: {e}"
        )
    return ConversationHandler.END

# ════════════════════════════════════════════════════════════
# InitDB2 flow (no PIN required)
# ════════════════════════════════════════════════════════════
async def initdb2_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for confirmation before resetting DB (no PIN)."""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="initdb2_yes"),
         InlineKeyboardButton("❌ No",  callback_data="initdb2_no")]
    ])
    await update.message.reply_text(
        "⚠️ *TEST MODE:* This will DELETE all data and create a fresh database.\n\n"
        "Are you sure you want to proceed?",
        parse_mode="Markdown", reply_markup=kb)
    return CONFIRM_INITDB2

async def initdb2_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "initdb2_no":
        await update.callback_query.edit_message_text("❌ InitDB2 cancelled.")
        return ConversationHandler.END

    db_path = config.DB_PATH

    try:
        # Wipe DB file
        if os.path.exists(db_path):
            os.remove(db_path)
            logging.warning(f"⚠️ Database file {db_path} deleted.")

        # Recreate DB (empty)
        if config.ENABLE_ENCRYPTION:
            await update.callback_query.edit_message_text(
                "⚠️ Encryption is enabled. Run /unlock with your PIN to set up the fresh DB."
            )
        else:
            secure_db.db = TinyDB(config.DB_PATH, storage=JSONStorage)
            await update.callback_query.edit_message_text(
                "✅ Database reset (InitDB2, no password)."
            )
            logging.info("✅ Database reset in InitDB2 (no PIN).")
    except Exception as e:
        logging.error(f"InitDB2 failed: {e}")
        await update.callback_query.edit_message_text(
            f"❌ InitDB2 failed: {e}"
        )
    return ConversationHandler.END

# ════════════════════════════════════════════════════════════
# Unlock command flow
# ════════════════════════════════════════════════════════════
UNLOCK_PIN = range(1)  # conversation state

async def unlock_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt admin for encryption PIN/key."""
    await update.message.reply_text("🔑 *Enter your encryption PIN to unlock:*", parse_mode="Markdown")
    return UNLOCK_PIN

async def unlock_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attempt to unlock the database with provided PIN."""
    pin = update.message.text.strip()
    try:
        secure_db.unlock(pin)
        secure_db.mark_activity()  # update last activity
        await update.message.reply_text("✅ *Database unlocked successfully!*", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Unlock failed: {e}")
        await update.message.reply_text(f"❌ *Unlock failed:* {e}", parse_mode="Markdown")
    return ConversationHandler.END

# ════════════════════════════════════════════════════════════
# Auto-lock background task
# ════════════════════════════════════════════════════════════
async def auto_lock_task():
    """Background coroutine to auto-lock DB after 3 min inactivity."""
    AUTOLOCK_TIMEOUT = 180  # 3 minutes
    while True:
        await asyncio.sleep(10)  # check every 10 seconds
        if secure_db.is_unlocked():
            now = time.monotonic()
            if now - secure_db.last_activity > AUTOLOCK_TIMEOUT:
                secure_db.lock()
                logging.warning("🔒 Auto-lock triggered after inactivity.")

# ════════════════════════════════════════════════════════════
# Menus
# ════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Root menu / back-to-root callback with lock status."""
    status_icon = "🔓 Unlocked" if secure_db.is_unlocked() else "🔒 Locked"

    kb = InlineKeyboardMarkup([
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

    # InitDB handlers
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("initdb", initdb_start)],
        states={
            CONFIRM_INITDB: [CallbackQueryHandler(initdb_confirm)],
            PASSWORD_INITDB: [MessageHandler(filters.TEXT & ~filters.COMMAND, initdb_password)],
        },
        fallbacks=[],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("initdb2", initdb2_start)],
        states={CONFIRM_INITDB2: [CallbackQueryHandler(initdb2_confirm)]},
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
    app.add_handler(CallbackQueryHandler(show_partner_sales_menu, pattern="^partner_sales_menu$"))

    # Reports
    register_customer_report_handlers(app)
    register_partner_report_handlers(app)
    app.add_handler(CallbackQueryHandler(show_partner_report_menu, pattern="^rep_part$"))
    register_store_report_handlers(app)
    app.add_handler(CallbackQueryHandler(show_store_report_menu, pattern="^rep_store$"))
    register_owner_report_handlers(app)
    app.add_handler(CallbackQueryHandler(show_owner_menu, pattern="^owner_menu$"))

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
# Simple self-supervisor — restarts on crash
# ════════════════════════════════════════════════════════════
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
