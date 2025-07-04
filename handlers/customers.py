handlers/customers.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ( ConversationHandler, CallbackQueryHandler, MessageHandler, CommandHandler, filters, ContextTypes ) from datetime import datetime from tinydb import Query from secure_db import secure_db

State constants

( C_NAME, C_CUR, C_CONFIRM, C_SEL_EDIT, C_NEW_NAME, C_NEW_CUR, C_CONFIRM_EDIT, C_SEL_REMOVE, C_CONFIRM_REMOVE, C_SEL_VIEW ) = range(10)

--- Handler implementations ---

async def ask_cust_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE): await update.callback_query.edit_message_text("Enter new customer name:") return C_NAME

async def ask_cust_cur(update: Update, ctx: ContextTypes.DEFAULT_TYPE): name = update.message.text.strip() ctx.user_data['cust_name'] = name kb = InlineKeyboardMarkup([ [InlineKeyboardButton(c, callback_data=c)] for c in ['USD','GBP','EUR'] ]) await update.message.reply_text("Select currency:", reply_markup=kb) return C_CUR

async def confirm_cust(update: Update, ctx: ContextTypes.DEFAULT_TYPE): cur = update.callback_query.data ctx.user_data['cust_cur'] = cur name, curcy = ctx.user_data['cust_name'], cur kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No",  callback_data='no')]]) await update.callback_query.edit_message_text( f"Confirm add:\n{name} ({curcy})?", reply_markup=kb) return C_CONFIRM

async def finalize_cust(update: Update, ctx: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': secure_db.insert('customers', { 'name': ctx.user_data['cust_name'], 'currency': ctx.user_data['cust_cur'], 'created_at': datetime.utcnow().isoformat() }) await update.callback_query.edit_message_text("✅ Customer added.") else: await update.callback_query.edit_message_text("❌ Operation cancelled.") return ConversationHandler.END

Edit Customer

async def select_cust_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('customers') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"cust_edit_{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='cancel')]) await update.callback_query.edit_message_text("Select customer to edit:", reply_markup=InlineKeyboardMarkup(buttons)) return C_SEL_EDIT

async def ask_cust_new_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) ctx.user_data['edit_cust_id'] = cid old = secure_db.all('customers')[cid-1]['name'] await update.callback_query.edit_message_text(f"Current name: {old}\nEnter new name:") return C_NEW_NAME

async def ask_cust_new_cur(update: Update, ctx: ContextTypes.DEFAULT_TYPE): new_name = update.message.text.strip() ctx.user_data['edit_cust_new_name'] = new_name kb = InlineKeyboardMarkup([[InlineKeyboardButton(c, callback_data=c)] for c in ['USD','GBP','EUR']]) await update.message.reply_text("Select new currency:", reply_markup=kb) return C_NEW_CUR

async def confirm_cust_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE): new_cur = update.callback_query.data ctx.user_data['edit_cust_new_cur'] = new_cur nm, cu = ctx.user_data['edit_cust_new_name'], new_cur kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No",  callback_data='no')]]) await update.callback_query.edit_message_text( f"Confirm update to: {nm} ({cu})?", reply_markup=kb) return C_CONFIRM_EDIT

async def finalize_cust_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': cid = ctx.user_data['edit_cust_id'] secure_db.update('customers', {'name': ctx.user_data['edit_cust_new_name'], 'currency': ctx.user_data['edit_cust_new_cur']}, doc_ids=[cid]) await update.callback_query.edit_message_text("✅ Customer updated.") else: await update.callback_query.edit_message_text("❌ Operation cancelled.") return ConversationHandler.END

Remove Customer

async def select_cust_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('customers') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"cust_rem_{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='cancel')]) await update.callback_query.edit_message_text("Select customer to remove:", reply_markup=InlineKeyboardMarkup(buttons)) return C_SEL_REMOVE

async def confirm_cust_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) ctx.user_data['remove_cust_id'] = cid name = secure_db.all('customers')[cid-1]['name'] kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data='yes'), InlineKeyboardButton("❌ No",  callback_data='no')]]) await update.callback_query.edit_message_text(f"Delete {name}?", reply_markup=kb) return C_CONFIRM_REMOVE

async def finalize_cust_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE): if update.callback_query.data == 'yes': secure_db.remove('customers', doc_ids=[ctx.user_data['remove_cust_id']]) await update.callback_query.edit_message_text("✅ Customer removed.") else: await update.callback_query.edit_message_text("❌ Operation cancelled.") return ConversationHandler.END

View Customer

async def select_cust_view(update: Update, ctx: ContextTypes.DEFAULT_TYPE): rows = secure_db.all('customers') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"cust_view_{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Back", callback_data='cancel')]) await update.callback_query.edit_message_text("Select customer to view:", reply_markup=InlineKeyboardMarkup(buttons)) return C_SEL_VIEW

async def show_cust_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE): cid = int(update.callback_query.data.split('_')[-1]) r = secure_db.all('customers')[cid-1] await update.callback_query.edit_message_text( f"👤 ID: {cid}\nName: {r['name']}\nCurrency: {r['currency']}\nCreated: {r['created_at']}" ) return ConversationHandler.END

Cancel fallback

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("❌ Operation cancelled.") return ConversationHandler.END

