#!/usr/bin/env python3
import logging
import asyncio
import os
import sys
import subprocess
import time
import re

import config
from secure_db import secure_db, EncryptedJSONStorage
from tinydb import TinyDB
from handlers.ledger import seed_tables  # 🌱 Correct import path for seeding
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

def is_strong_password(pw):
    if len(pw) < 8:
        return False
    if not re.search(r'[A-Z]', pw):
        return False
    if not re.search(r'[a-z]', pw):
        return False
    if not re.search(r'[0-9]', pw):
        return False
    if not re.search(r'[^A-Za-z0-9]', pw):
        return False
    return True

# Change PIN states (use high numbers to avoid conflict)
CHANGE_PIN_OLD, CHANGE_PIN_NEW, CHANGE_PIN_CONFIRM = range(100, 103)

# Core utilities
from handlers.utils import require_unlock, require_unlock_and_admin

# States for initdb conversation
CONFIRM_INITDB, ENTER_OLD_PIN, SET_NEW_PIN, CONFIRM_NEW_PIN = range(4)
UNLOCK_PIN = range(1)

# Feature modules
from handlers.customers         import register_customer_handlers,  show_customer_menu
from handlers.stores            import register_store_handlers,     show_store_menu
from handlers.partners          import register_partner_handlers,   show_partner_menu
from handlers.sales             import register_sales_handlers
from handlers.payments          import register_payment_handlers,   show_payment_menu
from handlers.expenses          import register_expense_handlers,   show_expense_menu
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

# ====== DIVIDENDS MODULE HANDLERS (UPDATED) ======
from handlers.dividends import (
    dividends_menu, handle_dividends_callback,
    start_credit_dividends, credit_select_debit_project, credit_select_credit_project, credit_amount_input, credit_confirm,
    start_withdraw_dividends, withdraw_select_project, withdraw_local_input, withdraw_fee_input, withdraw_usd_input, withdraw_confirm,
    start_project_expense, expense_select_credit_project, expense_select_debit_project, expense_local_paid_input, expense_local_received_input, expense_fee_input, expense_desc_input, expense_confirm,
    start_edit_delete,
    start_view_report, report_select_project, report_date_input, send_project_report,
    trace_all_messages,  # ✅ Add this here
)

from handlers.dividends import (
    DIV_DEBIT_PROJECT_SELECT, DIV_CREDIT_PROJECT_SELECT, DIV_CREDIT_AMOUNT, DIV_CREDIT_CONFIRM,
    DIV_WITHDRAW_PROJECT, DIV_WITHDRAW_LOCAL, DIV_WITHDRAW_FEE, DIV_WITHDRAW_USD, DIV_WITHDRAW_CONFIRM,
    DIV_EXPENSE_PROJECT_SELECT, DIV_EXPENSE_DEBIT_PROJECT_SELECT, DIV_EXPENSE_LOCAL_PAID, DIV_EXPENSE_LOCAL_RECEIVED, DIV_EXPENSE_FEE, DIV_EXPENSE_DESC, DIV_EXPENSE_CONFIRM,
    DIV_EDIT_TYPE,
    DIV_REPORT_PROJECT, DIV_REPORT_DATE,
)
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
# Change PIN flow
# ════════════════════════════════════════════════════════════
@require_unlock_and_admin
async def changepin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if hasattr(update, "message") and update.message:
        await update.message.reply_text("🔒 Enter your CURRENT PIN:")
    elif hasattr(update, "callback_query") and update.callback_query:
        await update.callback_query.message.reply_text("🔒 Enter your CURRENT PIN:")
    return CHANGE_PIN_OLD

async def changepin_check_old(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    if not secure_db.unlock(pin):
        await update.message.reply_text("❌ Incorrect PIN. Aborting.")
        return ConversationHandler.END
    context.user_data['old_pin'] = pin
    await update.message.reply_text("✅ Current PIN accepted.\nEnter your NEW PIN:")
    return CHANGE_PIN_NEW

async def changepin_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_pin = update.message.text.strip()
    if not is_strong_password(new_pin):
        await update.message.reply_text(
            "❌ PIN must be at least 8 characters, include uppercase, lowercase, a number, and a special character. Try again:"
        )
        return CHANGE_PIN_NEW
    context.user_data['new_pin'] = new_pin
    await update.message.reply_text("🔑 Confirm your NEW PIN:")
    return CHANGE_PIN_CONFIRM

async def changepin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    confirm_pin = update.message.text.strip()
    if confirm_pin != context.user_data.get('new_pin'):
        await update.message.reply_text("❌ New PINs do not match. Start over with /changepin.")
        return ConversationHandler.END

    old_pin = context.user_data.get('old_pin')
    new_pin = context.user_data.get('new_pin')
    try:
        all_data = secure_db.db.storage.read()
        secure_db.lock()
        secure_db.fernet = secure_db._derive_key(new_pin)
        secure_db.db = TinyDB(
            config.DB_PATH,
            storage=lambda p: EncryptedJSONStorage(p, secure_db.fernet)
        )
        secure_db.db.storage.write(all_data)
        secure_db.lock()
        await update.message.reply_text("✅ PIN changed successfully! Please use your new PIN from now on.")
        await start(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to change PIN: {e}")
    return ConversationHandler.END

# ════════════════════════════════════════════════════════════
# InitDB flow with secure setup script and enforced PIN
# ════════════════════════════════════════════════════════════
async def initdb_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not config.ENABLE_ENCRYPTION:
        await update.message.reply_text(
            "❌ Encryption must be enabled to initialize DB. Set ENABLE_ENCRYPTION = True in config.py."
        )
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="initdb_yes"),
         InlineKeyboardButton("❌ No",  callback_data="initdb_no")]
    ])
    if update.message:
        await update.message.reply_text(
            "⚠️ *This will DELETE all data and create a fresh encrypted database.*\n\n"
            "Are you sure you want to proceed?",
            parse_mode="Markdown", reply_markup=kb)
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            "⚠️ *This will DELETE all data and create a fresh encrypted database.*\n\n"
            "Are you sure you want to proceed?",
            parse_mode="Markdown", reply_markup=kb)
    return CONFIRM_INITDB

async def initdb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "initdb_no":
        await update.callback_query.edit_message_text("❌ InitDB cancelled.")
        return ConversationHandler.END

    if secure_db.has_pin():
        await update.callback_query.edit_message_text("🔒 Enter current DB password (PIN) to reset:")
        return ENTER_OLD_PIN

    await update.callback_query.edit_message_text("🔑 Enter new DB password (PIN):")
    return SET_NEW_PIN

async def enter_old_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    try:
        secure_db.unlock(pin)
        secure_db.lock()
        context.user_data["old_db_pin"] = pin
        await update.message.reply_text("🔑 Current PIN accepted. Enter new DB password (PIN):")
        return SET_NEW_PIN
    except Exception:
        await update.message.reply_text("❌ Wrong PIN. InitDB aborted.")
        return ConversationHandler.END

async def set_new_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    if not is_strong_password(pin):
        await update.message.reply_text(
            "❌ PIN must be at least 8 characters, include uppercase, lowercase, a number, and a special character. Try again:"
        )
        return SET_NEW_PIN
    context.user_data["new_db_pin"] = pin
    await update.message.reply_text("🔑 Confirm PIN by entering it again:")
    return CONFIRM_NEW_PIN

async def confirm_new_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    confirm_pin = update.message.text.strip()
    if confirm_pin != context.user_data.get("new_db_pin"):
        await update.message.reply_text(
            "❌ PINs do not match. Start over with /initdb."
        )
        return ConversationHandler.END

    if update.message:
        await update.message.reply_text("⚙️ Setting up secure DB (generating new salt)…")
    elif update.callback_query:
        await update.callback_query.message.reply_text("⚙️ Setting up secure DB (generating new salt)…")

    try:
        subprocess.run(["chmod", "+x", "./setup_secure_db.sh"], check=True)
        subprocess.run(["bash", "./setup_secure_db.sh"], check=True)
        logging.info("✅ setup_secure_db.sh executed successfully.")
    except Exception as e:
        logging.error(f"❌ setup_secure_db.sh failed: {e}")
        await update.message.reply_text("❌ Failed to run secure DB setup script.")
        return ConversationHandler.END

    pin = context.user_data["new_db_pin"].strip()
    secure_db._passphrase = pin
    secure_db.fernet = secure_db._derive_key(pin)
    secure_db.db = TinyDB(
        config.DB_PATH,
        storage=lambda p: EncryptedJSONStorage(p, secure_db.fernet)
    )

    seed_tables(secure_db)
    secure_db.lock()

    try:
        os.chmod("data/kdf_salt.bin", 0o444)
    except Exception as e:
        logging.warning(f"Failed to lock salt file as read-only: {e}")

    await update.message.reply_text(
        "✅ New PIN set and DB encrypted successfully.\n"
        "♻️ Restarting bot to apply changes…"
    )
    subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0]), "child"])
    raise SystemExit(0)
# ════════════════════════════════════════════════════════════
# Unlock command flow
# ════════════════════════════════════════════════════════════
async def unlock_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = getattr(config, "ADMIN_TELEGRAM_ID", None)
    user_id = (update.effective_user.id if update.effective_user else None)
    if user_id != admin_id:
        if hasattr(update, 'message') and update.message:
            await update.message.reply_text("❌ You are not authorized to unlock the database.")
        elif hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text("❌ You are not authorized to unlock the database.")
        return ConversationHandler.END

    context.user_data["unlock_attempts"] = 0
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text("🔑 *Enter your encryption PIN to unlock:*", parse_mode="Markdown")
    elif hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text("🔑 *Enter your encryption PIN to unlock:*", parse_mode="Markdown")
    return UNLOCK_PIN

async def unlock_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = getattr(config, "ADMIN_TELEGRAM_ID", None)
    user_id = (update.effective_user.id if update.effective_user else None)
    if user_id != admin_id:
        await update.message.reply_text("❌ You are not authorized to unlock the database.")
        return ConversationHandler.END

    pin = update.message.text.strip()
    success = secure_db.unlock(pin)
    if success:
        await update.message.reply_text("✅ *Database unlocked successfully!*", parse_mode="Markdown")
        await start(update, context)
        return ConversationHandler.END
    else:
        attempts = getattr(secure_db, "_failed_attempts", 0)
        left = max(0, getattr(secure_db, "MAX_PIN_ATTEMPTS", 7) - attempts)
        if left > 0:
            await update.message.reply_text(
                f"❌ *Unlock failed.* Attempts left: {left}\nTry again:",
                parse_mode="Markdown"
            )
            return UNLOCK_PIN
        else:
            await update.message.reply_text(
                "☠️ *Too many wrong attempts. DB wiped for security.*",
                parse_mode="Markdown"
            )
            return ConversationHandler.END

# ════════════════════════════════════════════════════════════
# Auto-lock background task
# ════════════════════════════════════════════════════════════
async def auto_lock_task():
    AUTOLOCK_TIMEOUT = 1800  # 30 minutes
    while True:
        await asyncio.sleep(10)
        if secure_db.is_unlocked():
            now = time.monotonic()
            try:
                last = secure_db.get_last_access()
            except AttributeError:
                last = now
            if now - last > AUTOLOCK_TIMEOUT:
                secure_db.lock()
                logging.warning("🔒 Auto-lock triggered after inactivity.")

# ════════════════════════════════════════════════════════════
# Main Menu and Nested Submenus
# ════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main menu with DB status indicator and unlock/initdb shortcuts."""
    if not os.path.exists(config.DB_PATH):
        status_icon = "📂 No DB found: run /initdb"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡️ InitDB", callback_data="initdb_menu")]
        ])
    elif secure_db.is_unlocked():
        status_icon = "🔓 Unlocked"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("ADD USER", callback_data="adduser_menu"),
             InlineKeyboardButton("ADD FINANCIAL", callback_data="addfinancial_menu")],
            [InlineKeyboardButton("👑 Owner", callback_data="owner_menu"),
             InlineKeyboardButton("📊 Reports", callback_data="report_menu")],
            [InlineKeyboardButton("🔑 Change PIN", callback_data="changepin_menu")],
        ])
    else:
        status_icon = "🔒 Locked"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 Unlock DB", callback_data="unlock_button")],
            [InlineKeyboardButton("⚡️ InitDB", callback_data="initdb_menu")],
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

@require_unlock_and_admin
async def show_adduser_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Customers", callback_data="customer_menu")],
        [InlineKeyboardButton("Stores",    callback_data="store_menu")],
        [InlineKeyboardButton("Partners",  callback_data="partner_menu")],
        [InlineKeyboardButton("🔙 Back",   callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text("ADD USER Menu:", reply_markup=kb)

@require_unlock_and_admin
async def show_addfinancial_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Sales",          callback_data="sales_menu")],
        [InlineKeyboardButton("Payments",       callback_data="payment_menu")],
        [InlineKeyboardButton("Expenses",       callback_data="expense_menu")],
        [InlineKeyboardButton("Payouts",        callback_data="payout_menu")],
        [InlineKeyboardButton("Stock-In",       callback_data="stockin_menu")],
        [InlineKeyboardButton("Partner Sales",  callback_data="partner_sales_menu")],
        [InlineKeyboardButton("Dividends",      callback_data="dividends_menu")],
        [InlineKeyboardButton("🔙 Back",        callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text("ADD FINANCIAL Menu:", reply_markup=kb)

@require_unlock_and_admin
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

@require_unlock_and_admin
async def show_changepin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await changepin_start(update, context)
dividends_conv = ConversationHandler(
    entry_points=[
        CommandHandler("dividends", dividends_menu),
        CallbackQueryHandler(handle_dividends_callback, pattern="^(div_credit|div_withdraw|div_expense|edit_delete|view_report|dividends_menu)$"),
    ],
    states={
        # CREDIT FLOW
        DIV_DEBIT_PROJECT_SELECT: [
            CallbackQueryHandler(credit_select_debit_project, pattern="^credit_debit_project_\\d+$"),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),  # 👈 Debug catch-all
        ],
        DIV_CREDIT_PROJECT_SELECT: [
            CallbackQueryHandler(credit_select_credit_project, pattern="^credit_credit_project_\\d+$"),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_CREDIT_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, credit_amount_input),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),  # 👈 Debug catch-all
        ],
        DIV_CREDIT_CONFIRM: [
            CallbackQueryHandler(credit_confirm, pattern="^credit_confirm$"),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],

        # WITHDRAW FLOW
        DIV_WITHDRAW_PROJECT: [
            CallbackQueryHandler(withdraw_select_project, pattern="^withdraw_project_\\d+$"),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_WITHDRAW_LOCAL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_local_input),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_WITHDRAW_FEE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_fee_input),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_WITHDRAW_USD: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_usd_input),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_WITHDRAW_CONFIRM: [
            CallbackQueryHandler(withdraw_confirm, pattern="^withdraw_confirm$"),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],

        # EXPENSE FLOW
        DIV_EXPENSE_PROJECT_SELECT: [
            CallbackQueryHandler(expense_select_credit_project, pattern="^expense_credit_project_\\d+$"),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_EXPENSE_DEBIT_PROJECT_SELECT: [
            CallbackQueryHandler(expense_select_debit_project, pattern="^expense_debit_project_\\d+$"),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_EXPENSE_LOCAL_PAID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, expense_local_paid_input),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_EXPENSE_LOCAL_RECEIVED: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, expense_local_received_input),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_EXPENSE_FEE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, expense_fee_input),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_EXPENSE_DESC: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, expense_desc_input),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_EXPENSE_CONFIRM: [
            CallbackQueryHandler(expense_confirm, pattern="^expense_confirm$"),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],

        # EDIT/DELETE
        DIV_EDIT_TYPE: [
            CallbackQueryHandler(start_edit_delete, pattern="^(edit_credits|edit_withdrawals|edit_expenses|dividends_menu)$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],

        # REPORT FLOW
        DIV_REPORT_PROJECT: [
            CallbackQueryHandler(report_select_project, pattern="^report_project_\\d+$"),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
        DIV_REPORT_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, report_date_input),
            CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
            MessageHandler(filters.ALL, trace_all_messages),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"),
        CommandHandler("dividends", dividends_menu),
        MessageHandler(filters.ALL, dividends_menu),  # fallback for stray messages
    ],
    allow_reentry=True,
    per_message=True,
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
        entry_points=[CommandHandler("initdb", initdb_start),
                      CallbackQueryHandler(initdb_start, pattern="^initdb_menu$")],
        states={
            CONFIRM_INITDB: [CallbackQueryHandler(initdb_confirm)],
            ENTER_OLD_PIN:  [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_old_pin)],
            SET_NEW_PIN:    [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_pin)],
            CONFIRM_NEW_PIN:[MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_new_pin)],
        },
        fallbacks=[],
    ))

    # Unlock handler
    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("unlock", unlock_start),
            CallbackQueryHandler(unlock_start, pattern="^unlock_button$"),
        ],
        states={UNLOCK_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, unlock_process)]},
        fallbacks=[],
    ))

    # Change PIN handler
    app.add_handler(ConversationHandler(
        entry_points=[
            CommandHandler("changepin", changepin_start),
            CallbackQueryHandler(changepin_start, pattern="^changepin_menu$"),
        ],
        states={
            CHANGE_PIN_OLD:    [MessageHandler(filters.TEXT & ~filters.COMMAND, changepin_check_old)],
            CHANGE_PIN_NEW:    [MessageHandler(filters.TEXT & ~filters.COMMAND, changepin_new)],
            CHANGE_PIN_CONFIRM:[MessageHandler(filters.TEXT & ~filters.COMMAND, changepin_confirm)],
        },
        fallbacks=[],
    ))

    # Root / back commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(show_adduser_menu, pattern="^adduser_menu$"))
    app.add_handler(CallbackQueryHandler(show_addfinancial_menu, pattern="^addfinancial_menu$"))
    app.add_handler(CallbackQueryHandler(show_report_menu, pattern="^report_menu$"))
    app.add_handler(CallbackQueryHandler(show_changepin_menu, pattern="^changepin_menu$"))
    app.add_handler(CallbackQueryHandler(dividends_menu, pattern="^dividends_menu$"))

    # **Register backup handlers BEFORE owner handlers!**
    from handlers.backup import register_backup_handlers
    register_backup_handlers(app)

    # Register feature handlers
    register_customer_handlers(app)
    register_store_handlers(app)
    register_partner_handlers(app)
    register_sales_handlers(app)
    register_payment_handlers(app)
    register_expense_handlers(app)
    app.add_handler(CallbackQueryHandler(show_expense_menu, pattern="^expense_menu$"))
    register_payout_handlers(app)
    app.add_handler(CallbackQueryHandler(show_payout_menu, pattern="^payout_menu$"))
    register_stockin_handlers(app)
    app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))
    register_partner_sales_handlers(app)
    app.add_handler(CallbackQueryHandler(show_partner_sales_menu, pattern="^partner_sales_menu$"))

    # Register owner handlers AFTER backup handlers
    register_owner_handlers(app)
    app.add_handler(CallbackQueryHandler(show_owner_menu, pattern="^owner_menu$"))

    # Reports
    register_customer_report_handlers(app)
    app.add_handler(CallbackQueryHandler(show_report_menu, pattern="^report_menu$"))
    register_partner_report_handlers(app)
    register_store_report_handlers(app)
    register_owner_report_handlers(app)

    # ====== DIVIDENDS MODULE HANDLER (ADDED) ======
    app.add_handler(dividends_conv)

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
