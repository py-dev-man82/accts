from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import ( Application, CallbackQueryHandler, MessageHandler, filters, ContextTypes ) from datetime import datetime from tinydb import Query from secure_db import secure_db

State constants

( PAY_CUST, PAY_LOCAL, PAY_FEE, PAY_USD, PAY_CONFIRM ) = range(5)

1. Select customer

async def select_payment_customer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query; await query.answer() rows = secure_db.all('customers') buttons = [[InlineKeyboardButton(r['name'], callback_data=f"pay_cust_{r.doc_id}")] for r in rows] buttons.append([InlineKeyboardButton("◀️ Cancel", callback_data='back_main')]) kb = InlineKeyboardMarkup(buttons) await query.edit_message_text("Select customer for payment:", reply_markup=kb) return PAY_CUST

2. Ask local amount

async def ask_payment_local(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query; await query.answer() cust_id = int(query.data.split('_')[-1]) context.user_data['pay_cust_id'] = cust_id await query.edit_message_text("Enter local currency amount received:") return PAY_LOCAL

3. Ask handling fee

async def ask_payment_fee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: try: amt = float(update.message.text) context.user_data['pay_local'] = amt await update.message.reply_text("Enter handling fee amount:") return PAY_FEE except ValueError: await update.message.reply_text("Invalid number. Please enter the local amount:") return PAY_LOCAL

4. Ask USD received

async def ask_payment_usd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: try: fee = float(update.message.text) context.user_data['pay_fee'] = fee await update.message.reply_text("Enter USD amount received:") return PAY_USD except ValueError: await update.message.reply_text("Invalid number. Please enter the handling fee:") return PAY_FEE

5. Confirm payment

async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: try: usd = float(update.message.text) local = context.user_data['pay_local'] fee = context.user_data['pay_fee'] fx = (local - fee) / usd context.user_data.update({'pay_usd': usd, 'pay_fx': fx}) # Fetch customer name and currency cust = secure_db.all('customers')[context.user_data['pay_cust_id']-1] text = ( f"💳 Payment Summary for {cust['name']}:\n" f"Local Amount: {local:.2f} {cust['currency']}\n" f"Handling Fee: {fee:.2f} {cust['currency']}\n" f"USD Received: ${usd:.2f}\n" f"FX Rate: {fx:.4f}\n\n" f"Confirm?" ) kb = InlineKeyboardMarkup([ [InlineKeyboardButton("✅ Yes", callback_data='pay_yes'), InlineKeyboardButton("❌ No",  callback_data='pay_no')] ]) await update.message.reply_text(text, reply_markup=kb) return PAY_CONFIRM except ValueError: await update.message.reply_text("Invalid number. Please enter the USD amount:") return PAY_USD

6. Finalize payment

async def finalize_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query; await query.answer() if query.data == 'pay_yes': secure_db.insert('customer_payments', { 'customer_id': context.user_data['pay_cust_id'], 'local_amount': context.user_data['pay_local'], 'fee': context.user_data['pay_fee'], 'fx_rate': context.user_data['pay_fx'], 'usd_amount': context.user_data['pay_usd'], 'created_at': datetime.utcnow().isoformat() }) await query.edit_message_text("✅ Payment recorded.") else: await query.edit_message_text("❌ Payment cancelled.") return ConversationHandler.END

Registration

def register_payment_handlers(app: Application) -> None: # Entry app.add_handler(CallbackQueryHandler(select_payment_customer, pattern='^add_payment$')) # Flow app.add_handler(CallbackQueryHandler(ask_payment_local,   pattern='^pay_cust_')) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_payment_fee), group=PAY_LOCAL) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_payment_usd), group=PAY_FEE) app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_payment), group=PAY_USD) app.add_handler(CallbackQueryHandler(finalize_payment,    pattern='^pay_(yes|no)$'))

