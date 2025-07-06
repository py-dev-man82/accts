handlers/customers.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ( ConversationHandler, CallbackQueryHandler, MessageHandler, CommandHandler, filters, ContextTypes, ) from datetime import datetime from tinydb import Query

from handlers.utils import require_unlock from secure_db import secure_db

State constants for the customer flow

( C_NAME,       # adding/editing: entering name C_CUR,        # entering currency code C_CONFIRM,    # confirm add/edit E_SELECT,     # selecting customer to edit/delete E_NAME,       # editing: new name E_CUR,        # editing: new currency E_CONFIRM,    # confirm edit D_CONFIRM     # confirm delete ) = range(8)

--- Add Customer ---

@require_unlock async def add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE): if update.callback_query: await update.callback_query.answer() await update.callback_query.edit_message_text("Enter new customer name:") else: await update.message.reply_text("Enter new customer name:") context.user_data['flow'] = 'add' return C_NAME

async def get_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE): name = update.message.text.strip() context.user_data['customer_name'] = name await update.message.reply_text( f"Name: {name}\nEnter currency code (e.g. USD):" ) return C_CUR

async def get_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE): cur = update.message.text.strip().upper() context.user_data['customer_currency'] = cur kb = InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data="cust_yes"), InlineKeyboardButton("❌ No",  callback_data="cust_no")] ]) await update.message.reply_text( f"Name: {context.user_data['customer_name']}\n" f"Currency: {cur}\nSave?", reply_markup=kb ) return C_CONFIRM

@require_unlock async def confirm_customer(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.callback_query.answer() data = update.callback_query.data if data == 'cust_yes' and context.user_data.get('flow') == 'add': secure_db.insert('customers', { 'name': context.user_data['customer_name'], 'currency': context.user_data['customer_currency'], 'created_at': datetime.utcnow().isoformat() }) await update.callback_query.edit_message_text( f"✅ Customer '{context.user_data['customer_name']}' added." ) elif data == 'cust_yes' and context.user_data.get('flow') == 'edit': cid = context.user_data['edit_id'] secure_db.update('customers', {'name': context.user_data['customer_name'], 'currency': context.user_data['customer_currency']}, [cid]) await update.callback_query.edit_message_text( f"✅ Customer '{context.user_data['customer_name']}' updated." ) else: await update.callback_query.edit_message_text("❌ Operation cancelled.") return ConversationHandler.END

--- Edit Customer ---

@require_unlock async def edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE): # fetch all customers customers = secure_db.all('customers') if not customers: await update.message.reply_text("No customers to edit.") return ConversationHandler.END buttons = [ [InlineKeyboardButton(c['name'], callback_data=f"edit_{i}")] for i, c in enumerate(customers) ] kb = InlineKeyboardMarkup(buttons) await update.message.reply_text("Select customer to edit:", reply_markup=kb) context.user_data['cust_list'] = customers return E_SELECT

async def select_customer(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.callback_query.answer() idx = int(update.callback_query.data.split('_')[1]) customer = context.user_data['cust_list'][idx] context.user_data['edit_id'] = customer.doc_id if hasattr(customer, 'doc_id') else idx context.user_data['customer_name'] = customer['name'] context.user_data['customer_currency'] = customer['currency'] await update.callback_query.edit_message_text( f"Editing '{customer['name']}'\n" f"Current currency: {customer['currency']}\n" f"Enter new name (or same):" ) return E_NAME

async def edit_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE): name = update.message.text.strip() context.user_data['customer_name'] = name await update.message.reply_text( f"Name: {name}\nEnter new currency code:" ) return E_CUR

async def edit_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE): cur = update.message.text.strip().upper() context.user_data['customer_currency'] = cur kb = InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data="cust_yes"), InlineKeyboardButton("❌ No",  callback_data="cust_no")] ]) await update.message.reply_text( f"Name: {context.user_data['customer_name']}\n" f"Currency: {cur}\nSave changes?", reply_markup=kb ) context.user_data['flow'] = 'edit' return C_CONFIRM

--- Delete Customer ---

@require_unlock async def delete_customer(update: Update, context: ContextTypes.DEFAULT_TYPE): customers = secure_db.all('customers') if not customers: await update.message.reply_text("No customers to delete.") return ConversationHandler.END buttons = [ [InlineKeyboardButton(c['name'], callback_data=f"del_{i}")] for i, c in enumerate(customers) ] kb = InlineKeyboardMarkup(buttons) await update.message.reply_text("Select customer to delete:", reply_markup=kb) context.user_data['cust_list'] = customers return D_CONFIRM

@require_unlock async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.callback_query.answer() idx = int(update.callback_query.data.split('_')[1]) customer = context.user_data['cust_list'][idx] secure_db.remove('customers', [customer.doc_id if hasattr(customer, 'doc_id') else idx]) await update.callback_query.edit_message_text( f"✅ Customer '{customer['name']}' deleted." ) return ConversationHandler.END

--- View Customers ---

@require_unlock async def view_customers(update: Update, context: ContextTypes.DEFAULT_TYPE): customers = secure_db.all('customers') if not customers: await update.message.reply_text("No customers found.") return lines = [f"• {c['name']} ({c['currency']})" for c in customers] await update.message.reply_text("Customers:\n" + "\n".join(lines))

--- Registration ---

def register_customer_handlers(app): add_conv = ConversationHandler( entry_points=[ CommandHandler("add_customer", add_customer), CallbackQueryHandler(add_customer, pattern="^add_customer$") ], states={ C_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_name)], C_CUR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_currency)], C_CONFIRM: [CallbackQueryHandler(confirm_customer, pattern="^cust_")] }, fallbacks=[CommandHandler("cancel", confirm_customer)], per_message=False ) edit_conv = ConversationHandler( entry_points=[ CommandHandler("edit_customer", edit_customer), CallbackQueryHandler(edit_customer, pattern="^edit_\d+") ], states={ E_SELECT: [CallbackQueryHandler(select_customer, pattern="^edit_\d+")], E_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_customer_name)], E_CUR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_customer_currency)], C_CONFIRM:[CallbackQueryHandler(confirm_customer, pattern="^cust_")] }, fallbacks=[CommandHandler("cancel", confirm_customer)], per_message=False ) del_conv = ConversationHandler( entry_points=[ CommandHandler("remove_customer", delete_customer), CallbackQueryHandler(delete_customer, pattern="^del_\d+") ], states={ D_CONFIRM: [CallbackQueryHandler(confirm_delete, pattern="^del_\d+")] }, fallbacks=[CommandHandler("cancel", confirm_delete)], per_message=False ) app.add_handler(add_conv) app.add_handler(edit_conv) app.add_handler(del_conv) app.add_handler(CommandHandler("view_customer", view_customers))

