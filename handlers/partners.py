from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ( CallbackQueryHandler, MessageHandler, CommandHandler, filters, ContextTypes, ConversationHandler ) from secure_db import SecureDB from datetime import datetime from tinydb import Query

SecureDB instance

secure_db = SecureDB

State constants

( P_NAME, P_CUR, P_CONFIRM, P_SEL_EDIT, P_NEW_NAME, P_NEW_CUR, P_CONFIRM_EDIT, P_SEL_REMOVE, P_CONFIRM_REMOVE, P_SEL_VIEW, ) = range(21)

Register partner CRUD handlers

def register_partner_handlers(app): # Add Partner app.add_handler(CallbackQueryHandler(ask_part_name,    pattern='^add_partner$')) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_part_cur), group=P_NAME) app.add_handler(CallbackQueryHandler(confirm_part,      pattern='^[A-Z]{3}$'), group=P_CUR) app.add_handler(CallbackQueryHandler(finalize_part,     pattern='^(yes|no)$'), group=P_CONFIRM)

# Edit Partner
app.add_handler(CallbackQueryHandler(select_part_edit,  pattern='^edit_partner$'))
app.add_handler(CallbackQueryHandler(ask_part_new_name, pattern='^part_edit_'), group=P_SEL_EDIT)
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_part_new_cur), group=P_NEW_NAME)
app.add_handler(CallbackQueryHandler(confirm_part_edit, pattern='^[A-Z]{3}$'), group=P_NEW_CUR)
app.add_handler(CallbackQueryHandler(finalize_part_edit, pattern='^(yes|no)$'), group=P_CONFIRM_EDIT)

# Remove Partner
app.add_handler(CallbackQueryHandler(select_part_remove, pattern='^remove_partner$'))
app.add_handler(CallbackQueryHandler(confirm_part_remove, pattern='^part_rem_'), group=P_SEL_REMOVE)
app.add_handler(CallbackQueryHandler(finalize_part_remove, pattern='^(yes|no)$'), group=P_CONFIRM_REMOVE)

# View Partner
app.add_handler(CallbackQueryHandler(select_part_view,    pattern='^view_partner$'))
app.add_handler(CallbackQueryHandler(show_part_details,   pattern='^part_view_'))

Handler implementations

async def ask_part_name(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.callback_query.edit_message_text("Enter new partner name:") return P_NAME

async def ask_part_cur(update: Update, context: ContextTypes.DEFAULT_TYPE): name = update.message.text.strip() context.user_data['part_name'] = name kb = InlineKeyboardMarkup([[InlineKeyboardButton(c, callback_data=c)] for c in ['GBP','USD','EUR']]) await update.message.reply_text("Select currency:", reply_markup=kb) return P_CUR

async def confirm_part(update: Update, context: ContextTypes.DEFAULT_TYPE): cur = update.callback_query.data context.user_data['part_cur'] = cur name = context.user_data['part_name'] await update.callback_query.edit_message_text( f"Confirm add:\n{name} ({cur})?", reply_markup=InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No", callback_data='no')] ]) ) return P_CONFIRM

async def finalize_part(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': secure_db.insert('partners', { 'name': context.user_data['part_name'], 'currency': context.user_data['part_cur'], 'created_at': datetime.utcnow().isoformat() }) await update.callback_query.edit_message_text("✅ Partner added.") else: await update.callback_query.edit_message_text("❌ Cancelled.") return ConversationHandler.END

async def select_part_edit(update: Update, context: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('partners') btns = [[InlineKeyboardButton(r['name'], callback_data=f"part_edit_{r.doc_id}")] for r in rows] btns.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) await update.callback_query.edit_message_text("Select partner to edit:", reply_markup=InlineKeyboardMarkup(btns)) return P_SEL_EDIT

async def ask_part_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) context.user_data['edit_part_id'] = cid name = secure_db.all('partners')[cid-1]['name'] await update.callback_query.edit_message_text(f"Current name: {name}\nEnter new name:") return P_NEW_NAME

async def ask_part_new_cur(update: Update, context: ContextTypes.DEFAULT_TYPE): new_name = update.message.text.strip() context.user_data['edit_part_new_name'] = new_name kb = InlineKeyboardMarkup([[InlineKeyboardButton(c, callback_data=c)] for c in ['GBP','USD','EUR']]) await update.message.reply_text("Select new currency:", reply_markup=kb) return P_NEW_CUR

async def confirm_part_edit(update: Update, context: ContextTypes.DEFAULT_TYPE): new_cur = update.callback_query.data context.user_data['edit_part_new_cur'] = new_cur nm, cu = context.user_data['edit_part_new_name'], new_cur await update.callback_query.edit_message_text( f"Confirm update to:\n{nm} ({cu})?", reply_markup=InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No", callback_data='no')] ]) ) return P_CONFIRM_EDIT

async def finalize_part_edit(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': pid = context.user_data['edit_part_id'] secure_db.update('partners', { 'name': context.user_data['edit_part_new_name'], 'currency': context.user_data['edit_part_new_cur'] }, doc_ids=[pid]) await update.callback_query.edit_message_text("✅ Partner updated.") else: await update.callback_query.edit_message_text("❌ Cancelled.") return ConversationHandler.END

async def select_part_remove(update: Update, context: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('partners') btns = [[InlineKeyboardButton(r['name'], callback_data=f"part_rem_{r.doc_id}")] for r in rows] btns.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) await update.callback_query.edit_message_text("Select partner to remove:", reply_markup=InlineKeyboardMarkup(btns)) return P_SEL_REMOVE

async def confirm_part_remove(update: Update, context: ContextTypes.DEFAULT_TYPE): pid = int(update.callback_query.data.split('_')[-1]) context.user_data['remove_part_id'] = pid name = secure_db.all('partners')[pid-1]['name'] await update.callback_query.edit_message_text( f"Delete {name}?", reply_markup=InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No", callback_data='no')] ]) ) return P_CONFIRM_REMOVE

async def finalize_part_remove(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': pid = context.user_data['remove_part_id'] secure_db.remove('partners', doc_ids=[pid]) await update.callback_query.edit_message_text("✅ Partner removed.") else: await update.callback_query.edit_message_text("❌ Cancelled.") return ConversationHandler.END

async def select_part_view(update: Update, context: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('partners') btns = [[InlineKeyboardButton(r['name'], callback_data=f"part_view_{r.doc_id}")] for r in rows] btns.append([InlineKeyboardButton("◀️ Back", callback_data='back_main')]) await update.callback_query.edit_message_text("Select partner to view:", reply_markup=InlineKeyboardMarkup(btns)) return P_SEL_VIEW

async def show_part_details(update: Update, context: ContextTypes.DEFAULT_TYPE): pid = int(update.callback_query.data.split('_')[-1]) r = secure_db.all('partners')[pid-1] await update.callback_query.edit_message_text( f"🤝 Partner Details\nID: {pid}\nName: {r['name']}\nCurrency: {r['currency']}\nCreated: {r['created_at']}" ) return ConversationHandler.END

