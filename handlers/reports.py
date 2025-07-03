from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import CallbackQueryHandler, Application, ConversationHandler, ContextTypes from datetime import datetime, date, timedelta from tinydb import Query from secure_db import secure_db

State constants

( REP_SEL_CUST, REP_SHOW_CUST, REP_SEL_PART, REP_SHOW_PART, REP_SEL_STORE, REP_SHOW_STORE ) = range(6)

Register report handlers

def register_report_handlers(app: Application): app.add_handler(CallbackQueryHandler(select_report_customer, pattern='^rep_customer$')) app.add_handler(CallbackQueryHandler(show_report_customer,   pattern='^report_cust_')) app.add_handler(CallbackQueryHandler(select_report_partner,  pattern='^rep_partner$')) app.add_handler(CallbackQueryHandler(show_report_partner,    pattern='^report_part_')) app.add_handler(CallbackQueryHandler(select_report_store,    pattern='^rep_store$')) app.add_handler(CallbackQueryHandler(show_report_store,      pattern='^report_store_')) app.add_handler(CallbackQueryHandler(show_report_owner,      pattern='^rep_owner$'))

Customer report flow

async def select_report_customer(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() rows = secure_db.all('customers') buttons = [[InlineKeyboardButton(r['name'], callback_data=f'report_cust_{r.doc_id}')] for r in rows] buttons.append([InlineKeyboardButton('◀️ Back', callback_data='back_main')]) await query.edit_message_text('Select a customer for weekly report:', reply_markup=InlineKeyboardMarkup(buttons)) return REP_SEL_CUST

async def show_report_customer(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() cid = int(query.data.split('_')[-1]) today = date.today() week_ago = today - timedelta(days=7) Q = Query() # Fetch sales sales = secure_db.search('customer_sales', (Q.customer_id == cid) & (Q.created_at.test(lambda d: week_ago <= datetime.fromisoformat(d).date() <= today)) ) # Fetch payments pays = secure_db.search('customer_payments', (Q.customer_id == cid) & (Q.created_at.test(lambda d: week_ago <= datetime.fromisoformat(d).date() <= today)) ) total_sales = sum(s['qty'] * s['unit_price'] for s in sales) total_usd   = sum(p['usd_amount'] for p in pays) lines = [ f"👤 Customer Weekly Report: ID {cid}", f"📆 {week_ago} → {today}", "", "🛒 Sales:"
] + [
f"- {s['created_at'][:10]} Item {s['item_id']} ×{s['qty']} @{s['unit_price']} → {s['qty'] * s['unit_price']:.2f}" for s in sales ] + [f"→ Total Sales: {total_sales:.2f}", "", "💳 Payments:"] + [ f"- {p['created_at'][:10]} Local {p['local_amount']:.2f}-{p['fee']:.2f} → ${p['usd_amount']:.2f} (FX {p['fx_rate']:.4f})" for p in pays ] + [f"→ Total USD Received: ${total_usd:.2f}"] await query.edit_message_text("\n".join(lines)) return ConversationHandler.END

Partner report flow

async def select_report_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() rows = secure_db.all('partners') buttons = [[InlineKeyboardButton(r['name'], callback_data=f'report_part_{r.doc_id}')] for r in rows] buttons.append([InlineKeyboardButton('◀️ Back', callback_data='back_main')]) await query.edit_message_text('Select a partner for weekly report:', reply_markup=InlineKeyboardMarkup(buttons)) return REP_SEL_PART

async def show_report_partner(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() pid = int(query.data.split('_')[-1]) today = date.today() week_ago = today - timedelta(days=7) Q = Query() # Inventory summary inv = secure_db.search('partner_inventory', Q.partner_id == pid) # Stock-in expenses si  = inv  # reuse inv entries if needed # Partner payouts payouts = secure_db.search('partner_payouts', (Q.partner_id == pid) & (Q.created_at.test(lambda d: week_ago <= datetime.fromisoformat(d).date() <= today)) ) # Construct lines (simplified) lines = [ f"🤝 Partner Weekly Report: ID {pid}", f"📆 {week_ago} → {today}", "", "📦 Inventory:"
] + [
f"- Item {r['item_id']} ×{r['qty']} @ cost {r.get('purchase_cost',0):.2f}" for r in inv ] + ["", "💸 Payouts:"] + [ f"- {p['created_at'][:10]} → ${p['amount_usd']:.2f}" for p in payouts ] await query.edit_message_text("\n".join(lines)) return ConversationHandler.END

Store report flow

async def select_report_store(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() rows = secure_db.all('stores') buttons = [[InlineKeyboardButton(r['name'], callback_data=f'report_store_{r.doc_id}')] for r in rows] buttons.append([InlineKeyboardButton('◀️ Back', callback_data='back_main')]) await query.edit_message_text('Select a store for weekly report:', reply_markup=InlineKeyboardMarkup(buttons)) return REP_SEL_STORE

async def show_report_store(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() sid = int(query.data.split('_')[-1]) today = date.today() week_ago = today - timedelta(days=7) Q = Query() # Inventory summary inv = secure_db.search('store_inventory', Q.store_id == sid) # Sales details sales = secure_db.search('customer_sales', (Q.store_id == sid) & (Q.created_at.test(lambda d: week_ago <= datetime.fromisoformat(d).date() <= today)) ) # Handling income fees = secure_db.search('store_handling_income', (Q.store_id == sid) & (Q.created_at.test(lambda d: week_ago <= datetime.fromisoformat(d).date() <= today)) ) lines = [ f"🏬 Store Weekly Report: ID {sid}", f"📆 {week_ago} → {today}", "", "📦 Inventory:"
] + [
f"- Item {r['item_id']} ×{r['qty']}" for r in inv ] + ["", "🛒 Sales:"] + [ f"- {s['created_at'][:10]} Item {s['item_id']}×{s['qty']} → {s['qty']*s['unit_price']:.2f}" for s in sales ] + ["", "💹 Fees Earned:"] + [ f"- {f['created_at'][:10]} → {f['total_fee']:.2f}" for f in fees ] await query.edit_message_text("\n".join(lines)) return ConversationHandler.END

Owner report (POT)

async def show_report_owner(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query; await query.answer() today = date.today() week_ago = today - timedelta(days=7) # POT summary pot = secure_db.all('pot')[-1] if secure_db.all('pot') else {} line = f"🛡️ Owner POT Balance: ${pot.get('current_balance', 0):.2f}\n(as of {pot.get('date', str(today))})" await query.edit_message_text(line) return ConversationHandler.END

