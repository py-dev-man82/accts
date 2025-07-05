bot.py

import logging from config import BOT_TOKEN, ADMIN_TELEGRAM_ID from secure_db import secure_db from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup from telegram.ext import ( ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, )

Decorator to require DB unlock before accessing data

from functools import wraps

def require_unlock(func): @wraps(func) async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE): try: secure_db.ensure_unlocked() except RuntimeError as e: if update.callback_query: await update.callback_query.answer(str(e), show_alert=True) else: await update.message.reply_text(str(e)) return return await func(update, context) return wrapper

Main menu

MENU_KEYBOARD = InlineKeyboardMarkup([ [ InlineKeyboardButton("👤 Customers", callback_data="add_customer"), InlineKeyboardButton("🏪 Stores",    callback_data="add_store"), InlineKeyboardButton("🤝 Partners", callback_data="add_partner"), ], [ InlineKeyboardButton("💰 Sales",    callback_data="add_sale"), InlineKeyboardButton("💵 Payments", callback_data="add_payment"), InlineKeyboardButton("🏦 Payouts",  callback_data="add_payout"), ], [ InlineKeyboardButton("📥 Stock-In", callback_data="add_stockin"), InlineKeyboardButton("📊 Reports",  callback_data="rep_owner"), InlineKeyboardButton("📄 Export",   callback_data="export_excel"), ], ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text( "Welcome! Please choose an option:", reply_markup=MENU_KEYBOARD )

Lock/Unlock handlers

def register_lock_handlers(app): async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE): if not context.args: await update.message.reply_text("Usage: /unlock <passphrase>") return passphrase = context.args[0] try: secure_db.unlock(passphrase) await update.message.reply_text("🔓 Database unlocked.") except Exception as e: await update.message.reply_text(f"Unlock failed: {e}")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secure_db.lock()
    await update.message.reply_text("🔒 Database locked.")

app.add_handler(CommandHandler("unlock", unlock_command))
app.add_handler(CommandHandler("lock",   lock_command))

Register feature handlers

def register_handlers(app): # Import inside function to ensure require_unlock is available from handlers.customers    import register_customer_handlers from handlers.stores       import register_store_handlers from handlers.partners     import register_partner_handlers from handlers.sales        import register_sales_handlers from handlers.payments     import register_payment_handlers from handlers.payouts      import register_payout_handlers from handlers.stockin      import register_stockin_handlers from handlers.reports      import register_report_handlers from handlers.export_excel import register_export_handler

register_customer_handlers(app)
register_store_handlers(app)
register_partner_handlers(app)
register_sales_handlers(app)
register_payment_handlers(app)
register_payout_handlers(app)
register_stockin_handlers(app)
register_report_handlers(app)
register_export_handler(app)

Bot entry point

def main(): logging.basicConfig(level=logging.INFO) app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
register_lock_handlers(app)
register_handlers(app)

app.run_polling()

if name == "main": main()

