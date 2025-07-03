from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ( Application, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler ) from secure_db import SecureDB import config from datetime import datetime from tinydb import Query

State constants

( S_NAME, S_CUR, S_CONFIRM, S_SEL_EDIT, S_NEW_NAME, S_NEW_CUR, S_CONFIRM_EDIT, S_SEL_REMOVE, S_CONFIRM_REMOVE, S_SEL_VIEW, ) = range(10)

secure_db = SecureDB(config.DB_PATH, config.DB_PASSPHRASE)

def register_store_handlers(app: Application): # Add Store app.add_handler(CallbackQueryHandler(ask_store_name, pattern='^add_store$')) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_store_cur), group=S_NAME) app.add_handler(CallbackQueryHandler(confirm_store), group=S_CUR) app.add_handler(CallbackQueryHandler(finalize_store), group=S_CONFIRM)

# Edit Store
app.add_handler(CallbackQueryHandler(select_store_edit, pattern='^edit_store$'))
app.add_handler(CallbackQueryHandler(ask_store_new_name, pattern='^str_edit_'), group=S_SEL_EDIT)
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_store_new_cur), group=S_NEW_NAME)
app.add_handler(CallbackQueryHandler(confirm_store_edit), group=S_NEW_CUR)
app.add_handler(CallbackQueryHandler(finalize_store_edit), group=S_CONFIRM_EDIT)

# Remove Store
app.add_handler(CallbackQueryHandler(select_store_remove, pattern='^remove_store$'))
app.add_handler(CallbackQueryHandler(confirm_store_remove, pattern='^str_rem_'), group=S_SEL_REMOVE)
app.add_handler(CallbackQueryHandler(finalize_store_remove), group=S_CONFIRM_REMOVE)

# View Store
app.add_handler(CallbackQueryHandler(select_store_view, pattern='^view_store$'))
app.add_handler(CallbackQueryHandler(show_store_details, pattern='^str_view_'), group=S_SEL_VIEW)

Handlers

async def ask_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.callback_query.edit_message_text("Enter new store name:") return S_NAME

async def ask_store_cur(update: Update, context: ContextTypes.DEFAULT_TYPE): name = update.message.text.strip() context.user_data['store_name'] = name kb = InlineKeyboardMarkup([[InlineKeyboardButton(c, callback_data=c)] for c in ['GBP','USD','EUR']]) await update.message.reply_text("Select currency:", reply_markup=kb) return S_CUR

async def confirm_store(update: Update, context: ContextTypes.DEFAULT_TYPE): cur = update.callback_query.data context.user_data['store_cur'] = cur name = context.user_data['store_name'] await update.callback_query.edit_message_text( f"Confirm add store:\n{name} ({cur})?", reply_markup=InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No", callback_data='no')] ]) ) return S_CONFIRM

async def finalize_store(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': secure_db.insert('stores', { 'name': context.user_data['store_name'], 'currency': context.user_data['store_cur'], 'created_at': datetime.utcnow().isoformat() }) await update.callback_query.edit_message_text("✅ Store added.") else: await update.callback_query.edit_message_text("❌ Cancelled.") return ConversationHandler.END

async def select_store_edit(update: Update, context: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('stores') btns = [[InlineKeyboardButton(r['name'], callback_data=f"str_edit_{r.doc_id}")] for r in rows] btns.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) await update.callback_query.edit_message_text("Select store to edit:", reply_markup=InlineKeyboardMarkup(btns)) return S_SEL_EDIT

async def ask_store_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) context.user_data['edit_store_id'] = cid name = secure_db.all('stores')[cid-1]['name'] await update.callback_query.edit_message_text(f"Current name: {name}\nEnter new name:") return S_NEW_NAME

async def ask_store_new_cur(update: Update, context: ContextTypes.DEFAULT_TYPE): new_name = update.message.text.strip() context.user_data['edit_store_new_name'] = new_name kb = InlineKeyboardMarkup([[InlineKeyboardButton(c, callback_data=c)] for c in ['GBP','USD','EUR']]) await update.message.reply_text("Select new currency:", reply_markup=kb) return S_NEW_CUR

async def confirm_store_edit(update: Update, context: ContextTypes.DEFAULT_TYPE): new_cur = update.callback_query.data context.user_data['edit_store_new_cur'] = new_cur nm, cu = context.user_data['edit_store_new_name'], new_cur await update.callback_query.edit_message_text( f"Confirm update to:\n{nm} ({cu})?", reply_markup=InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No", callback_data='no')] ]) ) return S_CONFIRM_EDIT

async def finalize_store_edit(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': cid = context.user_data['edit_store_id'] secure_db.update('stores', { 'name': context.user_data['edit_store_new_name'], 'currency': context.user_data['edit_store_new_cur'] }, doc_ids=[cid]) await update.callback_query.edit_message_text("✅ Store updated.") else: await update.callback_query.edit_message_text("❌ Cancelled.") return ConversationHandler.END

async def select_store_remove(update: Update, context: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('stores') btns = [[InlineKeyboardButton(r['name'], callback_data=f"str_rem_{r.doc_id}")] for r in rows] btns.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) await update.callback_query.edit_message_text("Select store to remove:", reply_markup=InlineKeyboardMarkup(btns)) return S_SEL_REMOVE

async def confirm_store_remove(update: Update, context: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) context.user_data['remove_store_id'] = cid name = secure_db.all('stores')[cid-1]['name'] await update.callback_query.edit_message_text( f"Delete {name}?", reply_markup=InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No", callback_data='no')] ]) ) return S_CONFIRM_REMOVE

async def finalize_store_remove(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': secure_db.remove('stores', doc_ids=[context.user_data['remove_store_id']]) await update.callback_query.edit_message_text("✅ Store removed.") else: await update.callback_query.edit_message_text("❌ Cancelled.") return ConversationHandler.END

async def select_store_view(update: Update, context: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('stores') btns = [[InlineKeyboardButton(r['name'], callback_data=f"str_view_{r.doc_id}")] for r in rows] btns.append([InlineKeyboardButton("◀️ Back", callback_data='back_main')]) await update.callback_query.edit_message_text("Select store to view:", reply_markup=InlineKeyboardMarkup(btns)) return S_SEL_VIEW

async def show_store_details(update: Update, context: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) r = secure_db.all('stores')[cid-1] await update.callback_query.edit_message_text( f"🏬 ID: {cid}\nName: {r['name']}\nCurrency: {r['currency']}\nCreated: {r['created_at']}" ) return ConversationHandler.END

