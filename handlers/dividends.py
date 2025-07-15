# handlers/dividends.py

import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

from secure_db import secure_db
from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import add_ledger_entry

logger = logging.getLogger("dividends")

# Conversation states
(
    DIV_PARTNER_SELECT,
    DIV_CREDIT_AMOUNT,
    DIV_CREDIT_CONFIRM,
    DIV_WITHDRAW_PARTNER,
    DIV_WITHDRAW_LOCAL,
    DIV_WITHDRAW_FEE,
    DIV_WITHDRAW_USD,
    DIV_WITHDRAW_CONFIRM,
) = range(8)

OWNER_ACCOUNT_ID = "POT"

# ════════════════════════════════════════════════════════════════════════
# Step 1: Credit Dividends Account
# ════════════════════════════════════════════════════════════════════════

@require_unlock
async def start_credit_dividends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    partners = [p for p in secure_db.all("partners") if p.get("dividends_account")]
    if not partners:
        await update.message.reply_text("❌ No partners with dividends accounts found.")
        return ConversationHandler.END
    
    buttons = [
        InlineKeyboardButton(p["name"], callback_data=f"div_credit_part_{p.doc_id}")
        for p in partners
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.message.reply_text("Select partner to credit dividends:", reply_markup=kb)
    return DIV_PARTNER_SELECT

async def get_credit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["partner_id"] = pid
    partner = secure_db.table("partners").get(doc_id=pid)
    cur = partner["currency"]
    await update.callback_query.edit_message_text(
        f"Enter amount to credit to dividends account ({cur}):"
    )
    return DIV_CREDIT_AMOUNT

async def get_credit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
        assert amt > 0
    except:
        await update.message.reply_text("❌ Enter a positive number:")
        return DIV_CREDIT_AMOUNT

    context.user_data["credit_amount"] = amt
    pid = context.user_data["partner_id"]
    partner = secure_db.table("partners").get(doc_id=pid)
    cur = partner["currency"]
    await update.message.reply_text(
        f"Confirm crediting {fmt_money(amt, cur)} to dividends account?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data="div_credit_conf_yes"),
             InlineKeyboardButton("❌ Cancel", callback_data="div_credit_conf_no")]
        ])
    )
    return DIV_CREDIT_CONFIRM

@require_unlock
async def confirm_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("no"):
        await update.callback_query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    pid = context.user_data["partner_id"]
    amt = context.user_data["credit_amount"]
    partner = secure_db.table("partners").get(doc_id=pid)
    cur = partner["currency"]
    today = datetime.now().strftime("%d%m%Y")
    ts = datetime.utcnow().isoformat()

    # Ledger entries
    add_ledger_entry(
        account_type="partner",
        account_id=pid,
        entry_type="payout",
        amount=-amt,
        currency=cur,
        note="Profit moved to dividends account",
        date=today,
        timestamp=ts,
    )
    add_ledger_entry(
        account_type="partner_dividends",
        account_id=pid,
        entry_type="dividend_credit",
        amount=amt,
        currency=cur,
        note="Profit credited to dividends account",
        date=today,
        timestamp=ts,
    )

    # Update dividends balance
    partner_div = partner.get("dividends_account", {})
    partner_div["balance"] = partner_div.get("balance", 0.0) + amt
    secure_db.update("partners", {"dividends_account": partner_div}, [pid])

    await update.callback_query.edit_message_text(f"✅ Credited {fmt_money(amt, cur)} to dividends account.")
    return ConversationHandler.END

# ════════════════════════════════════════════════════════════════════════
# Step 2: Withdraw From Dividends Account
# ════════════════════════════════════════════════════════════════════════

@require_unlock
async def start_withdraw_dividends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    partners = [p for p in secure_db.all("partners") if p.get("dividends_account")]
    if not partners:
        await update.message.reply_text("❌ No partners with dividends accounts found.")
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(p["name"], callback_data=f"div_withdraw_part_{p.doc_id}")
        for p in partners
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.message.reply_text("Select partner to withdraw dividends:", reply_markup=kb)
    return DIV_WITHDRAW_PARTNER

async def get_withdraw_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["partner_id"] = pid
    partner = secure_db.table("partners").get(doc_id=pid)
    cur = partner["currency"]
    bal = partner.get("dividends_account", {}).get("balance", 0.0)
    await update.callback_query.edit_message_text(
        f"Dividends balance: {fmt_money(bal, cur)}\nEnter withdrawal amount ({cur}):"
    )
    return DIV_WITHDRAW_LOCAL

async def get_withdraw_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
        assert amt > 0
    except:
        await update.message.reply_text("❌ Enter a positive number:")
        return DIV_WITHDRAW_LOCAL

    context.user_data["withdraw_local"] = amt
    await update.message.reply_text("Enter fee amount (same currency, 0 if none):")
    return DIV_WITHDRAW_FEE

async def get_withdraw_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee = float(update.message.text.strip())
        assert fee >= 0
    except:
        await update.message.reply_text("❌ Enter a non-negative number:")
        return DIV_WITHDRAW_FEE

    context.user_data["withdraw_fee"] = fee
    await update.message.reply_text("Enter USD amount paid:")
    return DIV_WITHDRAW_USD

async def get_withdraw_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd_amt = float(update.message.text.strip())
        assert usd_amt > 0
    except:
        await update.message.reply_text("❌ Enter a positive number:")
        return DIV_WITHDRAW_USD

    context.user_data["withdraw_usd"] = usd_amt
    
    pid = context.user_data["partner_id"]
    partner = secure_db.table("partners").get(doc_id=pid)
    cur = partner["currency"]
    amt = context.user_data["withdraw_local"]
    fee = context.user_data["withdraw_fee"]
    fx = (amt - fee) / usd_amt

    context.user_data["withdraw_fx"] = fx

    await update.message.reply_text(
        f"Confirm Withdrawal:\n"
        f"Partner: {partner['name']}\n"
        f"Withdrawal: {fmt_money(amt, cur)}\n"
        f"Fee: {fmt_money(fee, cur)}\n"
        f"USD Paid: {fmt_money(usd_amt, 'USD')}\n"
        f"FX Rate: {fx:.4f}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data="div_withdraw_conf_yes"),
             InlineKeyboardButton("❌ Cancel", callback_data="div_withdraw_conf_no")]
        ])
    )
    return DIV_WITHDRAW_CONFIRM

@require_unlock
async def confirm_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("no"):
        await update.callback_query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    pid = context.user_data["partner_id"]
    partner = secure_db.table("partners").get(doc_id=pid)
    cur = partner["currency"]
    amt = context.user_data["withdraw_local"]
    fee = context.user_data["withdraw_fee"]
    usd_amt = context.user_data["withdraw_usd"]
    fx = context.user_data["withdraw_fx"]
    today = datetime.now().strftime("%d%m%Y")
    ts = datetime.utcnow().isoformat()

    # Ledger entries
    add_ledger_entry(
        account_type="partner_dividends",
        account_id=pid,
        entry_type="dividend_withdrawal",
        amount=-amt,
        currency=cur,
        note="Dividends withdrawal",
        date=today,
        timestamp=ts,
    )
    add_ledger_entry(
        account_type="owner",
        account_id=OWNER_ACCOUNT_ID,
        entry_type="payout_sent",
        amount=-usd_amt,
        currency="USD",
        note="USD paid for dividends withdrawal",
        date=today,
        timestamp=ts,
        fee_amt=fee,
        fx_rate=fx,
        usd_amt=usd_amt,
    )
    if fee > 0:
        add_ledger_entry(
            account_type="owner",
            account_id=OWNER_ACCOUNT_ID,
            entry_type="fee",
            amount=fee,
            currency=cur,
            note="Handling fee for dividends withdrawal",
            date=today,
            timestamp=ts,
        )

    # Update dividends balance
    partner_div = partner.get("dividends_account", {})
    partner_div["balance"] = partner_div.get("balance", 0.0) - amt
    secure_db.update("partners", {"dividends_account": partner_div}, [pid])

    await update.callback_query.edit_message_text(f"✅ Withdrawal of {fmt_money(amt, cur)} recorded.")
    return ConversationHandler.END
