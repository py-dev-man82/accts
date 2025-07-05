bot.py

import logging from config import BOT_TOKEN, ADMIN_TELEGRAM_ID from secure_db import secure_db from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup from telegram.ext import ( ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, ) from functools import wraps

--- Decorator to require DB unlock before accessing data ---

def require_unlock(func): @wraps(func) async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE): try: secure_db.ensure_unlocked() except RuntimeError as e: # handle callback or message if update.callback_query: await update.callback_query.answer(str(e), show_alert=True) else: await update.message.reply_text(str(e)) return ConversationHandler.END return await func(update, context) return wrapper

--- Main menu keyboard ---

MENU_KEYBOARD = InlineKeyboardMarkup([ [ InlineKeyboardButton("👤 Customers", callback_data="add_customer"), InlineKeyboardButton("🏪 Stores",    callback_data="add_store"), ], [ InlineKeyboardButton("🤝 Partners", callback_data="add_partner"), InlineKeyboardButton("💰 Sales",    callback_data="add_sale"), ], [ InlineKeyboardButton("💳 Payments", callback_data="add_payment"), InlineKeyboardButton("🏦 Payouts",  callback_data="add_payout"), ], [ InlineKeyboardButton("📦 Stock-In", callback_data="add_stockin"), InlineKeyboardButton("📊 Reports",  callback_data="rep_owner"), ], [ InlineKeyboardButton("📁 Export Excel", callback_data="export_excel"), ], ])

--- /start handler ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): # Only allow admin to access if update.effective_user.id != ADMIN_TELEGRAM_ID: await update.message.reply_text("🚫 Unauthorized.") return await update.message.reply_text( "Welcome to Accounting Bot! Please choose an option:", reply_markup=MENU_KEYBOARD )

--- /unlock and /lock commands ---

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.effective_user.id != ADMIN_TELEGRAM_ID: await update.message.reply_text("🚫 Unauthorized.") return if not context.args: await update.message.reply_text("Usage: /unlock <passphrase>") return try: secure_db.unlock(context.args[0]) await update.message.reply_text("🔓 Database unlocked.") except Exception as e: await update.message.reply_text(f"❌ Unlock failed: {e}")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.effective_user.id != ADMIN_TELEGRAM_ID: await update.message.reply_text("🚫 Unauthorized.") return secure_db.lock() await update.message.reply_text("🔒 Database locked.")

--- Import and register your feature handlers ---

from handlers.customers     import register_customer_handlers from handlers.stores        import register_store_handlers from handlers.partners      import register_partner_handlers from handlers.sales         import register_sales_handlers from handlers.payments      import register_payment_handlers from handlers.payouts       import register_payout_handlers from handlers.stockin       import register_stockin_handlers from handlers.reports       import register_report_handlers from handlers.export_excel  import register_export_handler

--- Main ---

def main(): logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO) app = ApplicationBuilder().token(BOT_TOKEN).build()

# Basic commands
app.add_handler(CommandHandler('start', start))
app.add_handler(CommandHandler('unlock', unlock_command))
app.add_handler(CommandHandler('lock',   lock_command))

# CallbackQuery / inline-menu entry points
# Ensure each flow can start via inline button
app.add_handler(CallbackQueryHandler(start, pattern='^start$'))
app.add_handler(CallbackQueryHandler(unlock_command, pattern='^unlock$'))

# Register feature handlers
register_customer_handlers(app)
register_store_handlers(app)
register_partner_handlers(app)
register_sales_handlers(app)
register_payment_handlers(app)
register_payout_handlers(app)
register_stockin_handlers(app)
register_report_handlers(app)
register_export_handler(app)

# Run the bot
app.run_polling()

if name == 'main': main()

