# handlers/payouts.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from datetime import datetime
from tinydb import Query
from secure_db import secure_db

# State constants for Payout flow
(
    PO_PARTNER,
    PO_USD_AMOUNT,
    PO_CONFIRM
) = range(3)

# Register payout handlers
def register_payout_handlers(app):
    payout_conv = ConversationHandler(
        entry_points=[CommandHandler('add_payout', start_payout)],
        states={
            PO_PARTNER: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_payout_partner)],
            PO_USD_AMOUNT: [MessageHandler(filters.Regex(r'^\d+(\.\d{1,2})?$'), ask_payout_amount)],
            PO_CONFIRM: [CallbackQueryHandler(confirm_payout, pattern='^(payout_confirm|payout_cancel)$')]
        },
        fallbacks=[CommandHandler('cancel', cancel_payout)],
        allow_reentry=True,
    )
    app.add_handler(payout_conv)

# --- Payout flow handlers ---
async def start_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter partner ID for payout:")
    return PO_PARTNER

async def select_payout_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    partner_id = update.message.text.strip()
    context.user_data['payout_partner'] = partner_id
    await update.message.reply_text("Enter USD amount to payout:")
    return PO_USD_AMOUNT

async def ask_payout_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = float(update.message.text.strip())
    context.user_data['payout_amount'] = amount
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data='payout_confirm'),
        InlineKeyboardButton("❌ Cancel",  callback_data='payout_cancel')
    ]])
    await update.message.reply_text(
        f"Payout summary:\n" \
        f"Partner ID: {context.user_data['payout_partner']}\n" \
        f"Amount:     ${amount:.2f}",
        reply_markup=kb
    )
    return PO_CONFIRM

async def confirm_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == 'payout_confirm':
        secure_db.insert('partner_payouts', {
            'partner_id': context.user_data['payout_partner'],
            'amount_usd': context.user_data['payout_amount'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text("✅ Payout recorded.")
    else:
        await update.callback_query.edit_message_text("❌ Payout cancelled.")
    return ConversationHandler.END

async def cancel_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Payout entry cancelled.")
    return ConversationHandler.END
