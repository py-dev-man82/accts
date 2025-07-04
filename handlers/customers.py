handlers/customers.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ( ConversationHandler, CallbackQueryHandler, MessageHandler, CommandHandler, filters, ContextTypes ) from datetime import datetime from tinydb import Query from secure_db import secure_db

State constants for Customer CRUD flow

( C_NAME, C_CUR, C_CONFIRM, C_SEL_EDIT, C_NEW_NAME, C_NEW_CUR, C_CONFIRM_EDIT, C_SEL_REMOVE, C_CONFIRM_REMOVE, C_SEL_VIEW ) = range(10)

async def ask_cust_name(update: Update, context: ContextTypes.DEFAULT_TYPE): """Start add-customer flow.""" await update.callback_query.edit_message_text("Enter new customer name:") return C_NAME

async def ask_cust_cur(update: Update, context: ContextTypes.DEFAULT_TYPE): name = update.message.text.strip() context.user_data['cust_name'] = name buttons = [[InlineKeyboardButton(c, callback_data=c)] for c in ['GBP','USD','EUR']] kb = InlineKeyboardMarkup(buttons) await update.message.reply_text("Select currency:", reply_markup=kb) return C_CUR

async def confirm_cust(update: Update, context: ContextTypes.DEFAULT_TYPE): cur = update.callback_query.data context.user_data['cust_cur'] = cur name = context.user_data['cust_name'] kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No",  callback_data='no')]]) await update.callback_query.edit_message_text( f"Confirm add:\n{name} ({cur})?", reply_markup=kb) return C_CONFIRM

async def finalize_cust(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': name = context.user_data['cust_name'] cur  = context.user_data['cust_cur'] secure_db.insert('customers', { 'name': name, 'currency': cur, 'created_at': datetime.utcnow().isoformat() }) await update.callback_query.edit_message_text(f"✅ Added customer {name}.") else: await update.callback_query.edit_message_text("❌ Cancelled.") return ConversationHandler.END

Edit Customer

async def select_cust_edit(update: Update, context: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('customers') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"cust_edit_{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='cancel')]) kb = InlineKeyboardMarkup(buttons) await update.callback_query.edit_message_text("Select customer to edit:", reply_markup=kb) return C_SEL_EDIT

async def ask_cust_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) context.user_data['edit_cust_id'] = cid cust = secure_db.all('customers')[cid-1] await update.callback_query.edit_message_text( f"Current name: {cust['name']}\nEnter new name:") return C_NEW_NAME

async def ask_cust_new_cur(update: Update, context: ContextTypes.DEFAULT_TYPE): new_name = update.message.text.strip() context.user_data['edit_cust_new_name'] = new_name buttons = [[InlineKeyboardButton(c, callback_data=c)] for c in ['GBP','USD','EUR']] kb = InlineKeyboardMarkup(buttons) await update.message.reply_text("Select new currency:", reply_markup=kb) return C_NEW_CUR

async def confirm_cust_edit(update: Update, context: ContextTypes.DEFAULT_TYPE): new_cur = update.callback_query.data context.user_data['edit_cust_new_cur'] = new_cur nm = context.user_data['edit_cust_new_name'] kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No",  callback_data='no')]]) await update.callback_query.edit_message_text( f"Confirm update to:\n{nm} ({new_cur})?", reply_markup=kb) return C_CONFIRM_EDIT

async def finalize_cust_edit(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': cid = context.user_data['edit_cust_id'] secure_db.update('customers', { 'name': context.user_data['edit_cust_new_name'], 'currency': context.user_data['edit_cust_new_cur'] }, doc_ids=[cid]) await update.callback_query.edit_message_text("✅ Customer updated.") else: await update.callback_query.edit_message_text("❌ Cancelled.") return ConversationHandler.END

Remove Customer

async def select_cust_remove(update: Update, context: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('customers') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"cust_rem_{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='cancel')]) kb = InlineKeyboardMarkup(buttons) await update.callback_query.edit_message_text("Select customer to remove:", reply_markup=kb) return C_SEL_REMOVE

async def confirm_cust_remove(update: Update, context: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) context.user_data['remove_cust_id'] = cid name = secure_db.all('customers')[cid-1]['name'] kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No",  callback_data='no')]]) await update.callback_query.edit_message_text(f"Delete {name}?", reply_markup=kb) return C_CONFIRM_REMOVE

async def finalize_cust_remove(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': cid = context.user_data['remove_cust_id'] secure_db.remove('customers', doc_ids=[cid]) await update.callback_query.edit_message_text("✅ Customer removed.") else: await update.callback_query.edit_message_text("❌ Cancelled.") return ConversationHandler.END

View Customer

async def select_cust_view(update: Update, context: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('customers') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"cust_view_{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Back", callback_data='cancel')]) kb = InlineKeyboardMarkup(buttons) await update.callback_query.edit_message_text("Select customer to view:", reply_markup=kb) return C_SEL_VIEW

async def show_cust_details(update: Update, context: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) r = secure_db.all('customers')[cid-1] text = ( f"👤 ID: {cid}\n" f"Name: {r['name']}\n" f"Currency: {r['currency']}\n" f"Created: {r['created_at']}" ) await update.callback_query.edit_message_text(text) return ConversationHandler.END

Cancel handler

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query: await update.callback_query.answer() await update.callback_query.edit_message_text("❌ Cancelled.") else: await update.message.reply_text("❌ Cancelled.") return ConversationHandler.END

Registration

def register_customer_handlers(app): # Entry points app.add_handler(CallbackQueryHandler(ask_cust_name,    pattern='^add_customer$')) app.add_handler(CallbackQueryHandler(select_cust_edit,  pattern='^edit_customer$')) app.add_handler(CallbackQueryHandler(select_cust_remove,pattern='^remove_customer$')) app.add_handler(CallbackQueryHandler(select_cust_view,  pattern='^view_customer$')) # Handlers for each step app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_cust_cur),               group=C_NAME) app.add_handler(CallbackQueryHandler(confirm_cust,       pattern='^(GBP|USD|EUR)$')) app.add_handler(CallbackQueryHandler(finalize_cust,      pattern='^(yes|no)$')) app.add_handler(CallbackQueryHandler(ask_cust_new_name,  pattern='^cust_edit_\d+$')) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_cust_new_cur),           group=C_NEW_NAME) app.add_handler(CallbackQueryHandler(confirm_cust_edit,  pattern='^([A-Za-z]{3})$')) app.add_handler(CallbackQueryHandler(finalize_cust_edit, pattern='^(yes|no)$')) app.add_handler(CallbackQueryHandler(confirm_cust_remove,pattern='^cust_rem_\d+$')) app.add_handler(CallbackQueryHandler(finalize_cust_remove,pattern='^(yes|no)$')) app.add_handler(CallbackQueryHandler(show_cust_details,  pattern='^cust_view_\d+$')) app.add_handler(CommandHandler('cancel', cancel))

