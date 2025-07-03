from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import CallbackQueryHandler, MessageHandler, filters, ContextTypes, Application from secure_db import secure_db from tinydb import Query from datetime import datetime

State constants for sales flow

( SALE_SEL_CUST, SALE_SEL_STORE, SALE_SEL_ITEM, SALE_ASK_QTY, SALE_ASK_PRICE, SALE_ASK_NOTE, SALE_CONFIRM ) = range(7)

Register function to wire handlers

def register_sales_handlers(app: Application): # Entry: /start menu 'add_sale' callback app.add_handler(CallbackQueryHandler(select_sale_customer, pattern='^manage_sales$')) app.add_handler(CallbackQueryHandler(select_sale_customer, pattern='^add_sale$')) app.add_handler(CallbackQueryHandler(select_sale_store, pattern='^sale_cust_')) app.add_handler(CallbackQueryHandler(select_sale_item, pattern='^sale_store_')) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_sale_price), group=SALE_ASK_QTY) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_sale_note),  group=SALE_ASK_PRICE) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_sale),    group=SALE_ASK_NOTE) app.add_handler(CallbackQueryHandler(finalize_sale, pattern='^sale_(yes|no)$'), group=SALE_CONFIRM)

Handlers implementation

async def select_sale_customer(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() rows = secure_db.all('customers') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"sale_cust_{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) await query.edit_message_text("Select customer:", reply_markup=InlineKeyboardMarkup(buttons)) return SALE_SEL_CUST

async def select_sale_store(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() cust_id = int(query.data.split('')[-1]); context.user_data['sale_cust_id'] = cust_id rows = secure_db.all('stores') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"sale_store{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) await query.edit_message_text("Select store:", reply_markup=InlineKeyboardMarkup(buttons)) return SALE_SEL_STORE

async def select_sale_item(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() store_id = int(query.data.split('')[-1]); context.user_data['sale_store_id'] = store_id rows = secure_db.all('items') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"sale_item{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) await query.edit_message_text("Select item:", reply_markup=InlineKeyboardMarkup(buttons)) return SALE_SEL_ITEM

async def ask_sale_qty(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() item_id = int(query.data.split('_')[-1]); context.user_data['sale_item_id'] = item_id await query.edit_message_text("Enter quantity:") return SALE_ASK_QTY

async def ask_sale_price(update: Update, context: ContextTypes.DEFAULT_TYPE): qty_text = update.message.text try: qty = int(qty_text); context.user_data['sale_qty'] = qty except ValueError: await update.message.reply_text("Please enter a valid integer quantity:") return SALE_ASK_QTY await update.message.reply_text("Enter unit price (local currency):") return SALE_ASK_PRICE

async def ask_sale_note(update: Update, context: ContextTypes.DEFAULT_TYPE): price_text = update.message.text try: price = float(price_text); context.user_data['sale_price'] = price except ValueError: await update.message.reply_text("Please enter a valid number for price:") return SALE_ASK_PRICE await update.message.reply_text("Enter an optional note (or 'none'):") return SALE_ASK_NOTE

async def confirm_sale(update: Update, context: ContextTypes.DEFAULT_TYPE): note = update.message.text.strip() if note.lower() == 'none': note = '' context.user_data['sale_note'] = note

# Build summary
cust = secure_db.all('customers')[context.user_data['sale_cust_id']-1]['name']
store= secure_db.all('stores')[context.user_data['sale_store_id']-1]['name']
item = secure_db.all('items')[context.user_data['sale_item_id']-1]['name']
qty  = context.user_data['sale_qty']
price= context.user_data['sale_price']
total= qty * price
text = (
    f"🛒 Sale Summary:\n"
    f"Customer: {cust}\n"
    f"Store:    {store}\n"
    f"Item:     {item}\n"
    f"Quantity: {qty}\n"
    f"Unit Pr:  {price:.2f}\n"
    f"Total:    {total:.2f}\n"
    f"Note:     {note or '—'}"
)
kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data='sale_yes'),
                             InlineKeyboardButton("❌ Cancel", callback_data='sale_no')]])
await update.message.reply_text(text, reply_markup=kb)
return SALE_CONFIRM

async def finalize_sale(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() if query.data == 'sale_yes': # Insert sale record secure_db.insert('customer_sales', { 'customer_id': context.user_data['sale_cust_id'], 'store_id':    context.user_data['sale_store_id'], 'item_id':     context.user_data['sale_item_id'], 'qty':         context.user_data['sale_qty'], 'unit_price':  context.user_data['sale_price'], 'note':        context.user_data['sale_note'], 'created_at':  datetime.utcnow().isoformat() }) # TODO: deduct inventory and record handling fees here await query.edit_message_text(f"✅ Recorded sale total {context.user_data['sale_qty']*context.user_data['sale_price']:.2f}.") else: await query.edit_message_text("❌ Sale cancelled.") return ConversationHandler.END

