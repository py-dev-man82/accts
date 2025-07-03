from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import CallbackQueryHandler, MessageHandler, filters, ContextTypes, Application from datetime import datetime from tinydb import Query from secure_db import secure_db

State constants for Stock-In flow

SI_PART,   # select partner
SI_ITEM,   # select item
SI_QTY,    # enter quantity
SI_COST,   # enter purchase cost
SI_CONFIRM # confirm stock-in

 = range

1. Select partner

async def select_stockin_partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query; await query.answer() partners = secure_db.all('partners') buttons = [[InlineKeyboardButton(p['name'], callback_data=f"si_part_{p.doc_id}")] for p in partners] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) await query.edit_message_text("Select partner for stock-in:", reply_markup=InlineKeyboardMarkup(buttons)) return SI_PART

2. Select item

async def select_stockin_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query; await query.answer() part_id = int(query.data.split('')[-1]) context.user_data['si_part_id'] = part_id items = secure_db.all('items') buttons = [[InlineKeyboardButton(i['name'], callback_data=f"si_item{i.doc_id}")] for i in items] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) await query.edit_message_text("Select item to stock-in:", reply_markup=InlineKeyboardMarkup(buttons)) return SI_ITEM

3. Ask quantity

async def ask_stockin_qty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query; await query.answer() item_id = int(query.data.split('_')[-1]) context.user_data['si_item_id'] = item_id await query.edit_message_text("Enter quantity to add to inventory:") return SI_QTY

4. Ask purchase cost

async def ask_stockin_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: try: qty = int(update.message.text) if qty <= 0: raise ValueError context.user_data['si_qty'] = qty await update.message.reply_text("Enter purchase cost per unit (USD):") return SI_COST except ValueError: await update.message.reply_text("Please enter a valid positive integer for quantity:") return SI_QTY

5. Confirm stock-in

async def confirm_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: try: cost = float(update.message.text) if cost <= 0: raise ValueError context.user_data['si_cost'] = cost pid = context.user_data['si_part_id'] iid = context.user_data['si_item_id'] qty = context.user_data['si_qty'] text = ( f"📦 Stock-In Summary:\n" f"Partner ID: {pid}\n" f"Item ID:    {iid}\n" f"Quantity:   {qty}\n" f"Unit Cost:  {cost:.2f}\n" f"Total Cost: {qty * cost:.2f}" ) kb = InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data='si_yes'), InlineKeyboardButton("❌ No",  callback_data='si_no')] ]) await update.message.reply_text(text, reply_markup=kb) return SI_CONFIRM except ValueError: await update.message.reply_text("Please enter a valid positive number for cost:") return SI_COST

6. Finalize stock-in

async def finalize_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query; await query.answer() if query.data == 'si_yes': secure_db.insert('partner_inventory', { 'partner_id': context.user_data['si_part_id'], 'item_id':    context.user_data['si_item_id'], 'qty':        context.user_data['si_qty'], 'purchase_cost': context.user_data['si_cost'], 'created_at': datetime.utcnow().isoformat() }) await query.edit_message_text("✅ Stock-In recorded.") else: await query.edit_message_text("❌ Stock-In cancelled.") return MAIN_MENU

Registration function

def register_stockin_handlers(app: Application): app.add_handler(CallbackQueryHandler(select_stockin_partner, pattern='^add_stockin$')) app.add_handler(CallbackQueryHandler(select_stockin_item,  pattern='^si_part_')) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_stockin_qty), group=SI_ITEM) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_stockin_cost), group=SI_QTY) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_stockin), group=SI_COST) app.add_handler(CallbackQueryHandler(finalize_stockin, pattern='^si_(yes|no)$'))

