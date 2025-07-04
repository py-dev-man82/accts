handlers/partners.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ( ConversationHandler, CallbackQueryHandler, MessageHandler, CommandHandler, filters, ContextTypes ) from datetime import datetime from tinydb import Query from secure_db import secure_db

State constants for Partner CRUD flow

( P_NAME, P_CUR, P_CONFIRM, P_SEL_EDIT, P_NEW_NAME, P_NEW_CUR, P_CONFIRM_EDIT, P_SEL_REMOVE, P_CONFIRM_REMOVE, P_SEL_VIEW ) = range(10)

def register_partner_handlers(app): partner_conv = ConversationHandler( entry_points=[ CommandHandler('add_partner', add_partner), CommandHandler('edit_partner', edit_partner), CommandHandler('remove_partner', remove_partner), CommandHandler('view_partner', view_partner), ], states={ P_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_name)], P_CUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_currency)], P_CONFIRM: [CallbackQueryHandler(confirm_partner)], P_SEL_EDIT: [CallbackQueryHandler(select_edit_partner)], P_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_partner_name)], P_NEW_CUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_partner_currency)], P_CONFIRM_EDIT: [CallbackQueryHandler(confirm_edit_partner)], P_SEL_REMOVE: [CallbackQueryHandler(select_remove_partner)], P_CONFIRM_REMOVE: [CallbackQueryHandler(confirm_remove_partner)], P_SEL_VIEW: [CallbackQueryHandler(view_partner_details)], }, fallbacks=[CommandHandler('cancel', cancel_partner)], allow_reentry=True ) app.add_handler(partner_conv)

--- Add Partner ---

async def add_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Enter new partner name:") return P_NAME

async def get_partner_name(update: Update, context: ContextTypes.DEFAULT_TYPE): name = update.message.text.strip() context.user_data['partner_name'] = name await update.message.reply_text(f"Partner name '{name}'. Now enter currency:") return P_CUR

async def get_partner_currency(update: Update, context: ContextTypes.DEFAULT_TYPE): cur = update.message.text.strip() context.user_data['partner_currency'] = cur kb = InlineKeyboardMarkup([[ InlineKeyboardButton("✅ Yes", callback_data='partner_yes'), InlineKeyboardButton("❌ No",  callback_data='partner_no') ]]) await update.message.reply_text( f"Currency: {cur}\nSave this partner?", reply_markup=kb ) return P_CONFIRM

async def confirm_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'partner_yes': secure_db.insert('partners', { 'name': context.user_data['partner_name'], 'currency': context.user_data['partner_currency'], 'created_at': datetime.utcnow().isoformat() }) await update.callback_query.edit_message_text( f"✅ Partner '{context.user_data['partner_name']}' added." ) else: await update.callback_query.edit_message_text("❌ Add cancelled.") return ConversationHandler.END

--- Edit Partner (placeholders) ---

async def edit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Edit feature not implemented.") return ConversationHandler.END

async def select_edit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): return ConversationHandler.END

async def new_partner_name(update: Update, context: ContextTypes.DEFAULT_TYPE): return ConversationHandler.END

async def new_partner_currency(update: Update, context: ContextTypes.DEFAULT_TYPE): return ConversationHandler.END

async def confirm_edit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): return ConversationHandler.END

--- Remove Partner ---

async def remove_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Remove feature not implemented.") return ConversationHandler.END

async def select_remove_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): return ConversationHandler.END

async def confirm_remove_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): return ConversationHandler.END

--- View Partner ---

async def view_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("View feature not implemented.") return ConversationHandler.END

async def view_partner_details(update: Update, context: ContextTypes.DEFAULT_TYPE): return ConversationHandler.END

--- Cancel Handler ---

async def cancel_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Operation cancelled.") return ConversationHandler.END

