from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update from telegram.ext import CallbackQueryHandler, MessageHandler, filters, ContextTypes from datetime import datetime from tinydb import Query from secure_db import secure_db

State constants for partner payouts

( PO_PART,  # select partner PO_USD,   # enter USD amount PO_CONFIRM  # confirm payout ) = range(3)

1. Select partner

async def select_payout_partner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query await query.answer() partners = secure_db.all('partners') buttons = [ [InlineKeyboardButton(p['name'], callback_data=f"payout_{p.doc_id}")] for p in partners ] buttons.append([InlineKeyboardButton('◀️ Cancel', callback_data='back_main')]) kb = InlineKeyboardMarkup(buttons) await query.edit_message_text('Select a partner to pay:', reply_markup=kb) return PO_PART

2. Enter USD amount

async def ask_payout_usd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query await query.answer() part_id = int(query.data.split('_')[-1]) context.user_data['po_part_id'] = part_id await query.edit_message_text('Enter USD amount to payout:') return PO_USD

3. Confirm payout

async def confirm_payout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: try: usd_amount = float(update.message.text) context.user_data['po_usd_amount'] = usd_amount except ValueError: await update.message.reply_text('Please enter a valid number for USD amount:') return PO_USD

part_id = context.user_data['po_part_id']
# fetch partner name
partner = secure_db.all('partners')[part_id-1]
name = partner['name']
text = (
    f"🤝 Payout Summary:\n"
    f"Partner: {name}\n"
    f"Amount: ${usd_amount:.2f}\n\n"
    f"Confirm payout?"
)
kb = InlineKeyboardMarkup([
    [InlineKeyboardButton('✅ Yes', callback_data='po_yes'),
     InlineKeyboardButton('❌ No',  callback_data='po_no')]
])
await update.message.reply_text(text, reply_markup=kb)
return PO_CONFIRM

4. Finalize payout

async def finalize_payout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query await query.answer() if query.data == 'po_yes': part_id = context.user_data['po_part_id'] usd_amount = context.user_data['po_usd_amount'] secure_db.insert('partner_payouts', { 'partner_id': part_id, 'amount_usd': usd_amount, 'created_at': datetime.utcnow().isoformat() }) await query.edit_message_text(f"✅ Payout of ${usd_amount:.2f} recorded.") else: await query.edit_message_text('❌ Payout cancelled.') return ConversationHandler.END

Registration function to wire handlers into the application

def register_payout_handlers(application): application.add_handler(CallbackQueryHandler(select_payout_partner, pattern='^add_payout$')) application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_payout), group=PO_USD) application.add_handler(CallbackQueryHandler(confirm_payout, pattern='^payout_'), group=PO_PART) application.add_handler(CallbackQueryHandler(finalize_payout, pattern='^po_yes|po_no$'), group=PO_CONFIRM)

