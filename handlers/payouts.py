# handlers/payouts.py

import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from handlers.utils import require_unlock
from secure_db import secure_db

# State constants
(
    P_PARTNER_SELECT,
    P_LOCAL_AMT,
    P_FEE_PERC,
    P_USD_PAID,
    P_NOTE,
    P_CONFIRM,
    P_EDIT_PARTNER,
    P_EDIT_SELECT,
    P_EDIT_LOCAL,
    P_EDIT_FEE,
    P_EDIT_USD,
    P_EDIT_NOTE,
    P_EDIT_CONFIRM,
    P_DELETE_PARTNER,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM,
) = range(16)


# --- Submenu for Payouts ---
async def show_payout_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing payout submenu")
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Payout",    callback_data="add_payout")],
        [InlineKeyboardButton("👀 View Payouts", callback_data="view_payout")],
        [InlineKeyboardButton("✏️ Edit Payout",  callback_data="edit_payout")],
        [InlineKeyboardButton("🗑️ Remove Payout", callback_data="remove_payout")],
        [InlineKeyboardButton("🔙 Main Menu",    callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text(
        "Payouts: choose an action", reply_markup=kb
    )


# --- Add Payout Flow ---
@require_unlock
async def add_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all('partners')
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners available.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(p['name'], callback_data=f"pout_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a partner:", reply_markup=kb)
    return P_PARTNER_SELECT


async def get_payout_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data['partner_id'] = pid
    await update.callback_query.edit_message_text("Enter local amount to pay:")
    return P_LOCAL_AMT


async def get_payout_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text)
        if amt <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a valid positive number.")
        return P_LOCAL_AMT

    context.user_data['local_amt'] = amt
    await update.message.reply_text("Enter handling fee % (e.g. 2.5), or 0 if none:")
    return P_FEE_PERC


async def get_payout_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee_pct = float(update.message.text)
        if not (0 <= fee_pct < 100):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Enter a fee percentage between 0 and 100.")
        return P_FEE_PERC

    data = context.user_data
    data['fee_perc'] = fee_pct
    data['fee_amt'] = data['local_amt'] * fee_pct / 100.0
    await update.message.reply_text(
        f"Fee: {fee_pct:.2f}% → {data['fee_amt']:.2f}. Now enter USD paid:"
    )
    return P_USD_PAID


async def get_payout_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return P_USD_PAID

    context.user_data['usd_amt'] = usd
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 Add Note", callback_data="note_yes"),
        InlineKeyboardButton("⏭️ Skip Note", callback_data="note_skip"),
    ]])
    await update.message.reply_text("Optional: add a note?", reply_markup=kb)
    return P_NOTE


async def get_payout_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handles both the callback buttons and the follow-up text
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.data == 'note_skip':
            context.user_data['note'] = ""
            return await confirm_payout_prompt(update, context)
        else:  # 'note_yes'
            await update.callback_query.edit_message_text("Enter note text:")
            return P_NOTE
    else:
        # This is the user sending the actual note
        note = update.message.text.strip()
        context.user_data['note'] = note
        return await confirm_payout_prompt(update, context)


async def confirm_payout_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    local   = data['local_amt']
    fee_pct = data.get('fee_perc', 0)
    fee_amt = data.get('fee_amt', 0)
    usd     = data['usd_amt']
    net     = local - fee_amt
    fx      = net / usd if usd else 0

    summary = (
        f"Local: {local:.2f}\n"
        f"Fee: {fee_pct:.2f}% ({fee_amt:.2f})\n"
        f"USD Paid: {usd:.2f}\n"
        f"FX Rate: {fx:.4f}\n"
        f"Note: {data.get('note','')}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="pout_conf_yes"),
        InlineKeyboardButton("❌ No",  callback_data="pout_conf_no"),
    ]])
    await update.callback_query.edit_message_text(summary, reply_markup=kb)
    return P_CONFIRM


@require_unlock
async def confirm_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'pout_conf_yes':
        data = context.user_data
        rec = {
            'partner_id': data['partner_id'],
            'local_amt':  data['local_amt'],
            'fee_perc':   data['fee_perc'],
            'fee_amt':    data['fee_amt'],
            'usd_amt':    data['usd_amt'],
            'fx_rate':    (data['local_amt'] - data['fee_amt']) / data['usd_amt'] if data['usd_amt'] else 0,
            'note':       data.get('note',''),
            'timestamp':  datetime.utcnow().isoformat(),
        }
        secure_db.insert('partner_payouts', rec)
        await update.callback_query.edit_message_text(
            f"✅ Payout of {data['local_amt']:.2f} recorded.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
        )
    else:
        await show_payout_menu(update, context)
    return ConversationHandler.END


# --- View Payouts Flow ---
async def view_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View payouts")
    await update.callback_query.answer()
    rows = secure_db.all('partner_payouts')
    if not rows:
        text = "No payouts found."
    else:
        lines = []
        for r in rows:
            p = secure_db.table('partners').get(doc_id=r['partner_id'])
            name = p['name'] if p else 'Unknown'
            fee_pct = r.get('fee_perc', 0)
            fee_amt = r.get('fee_amt', 0)
            lines.append(
                f"[{r.doc_id}] {name}: {r['local_amt']:.2f} "
                f"(fee {fee_pct:.2f}%={fee_amt:.2f}) => {r['usd_amt']:.2f} USD"
            )
        text = "Payouts:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)


# --- (Edit & Delete flows remain unchanged) ---


def register_payout_handlers(app):
    app.add_handler(CallbackQueryHandler(show_payout_menu, pattern="^payout_menu$"))

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_payout", add_payout),
            CallbackQueryHandler(add_payout, pattern="^add_payout$")
        ],
        states={
            P_PARTNER_SELECT: [CallbackQueryHandler(get_payout_partner, pattern="^pout_\\d+$")],
            P_LOCAL_AMT:      [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_local)],
            P_FEE_PERC:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_fee)],
            P_USD_PAID:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_usd)],
            P_NOTE:           [
                CallbackQueryHandler(get_payout_note, pattern="^(note_skip|note_yes)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_payout_note),
            ],
            P_CONFIRM:        [CallbackQueryHandler(confirm_payout, pattern="^pout_conf_")],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: show_payout_menu(u,c))],
        per_message=False,
    )
    app.add_handler(add_conv)

    app.add_handler(CallbackQueryHandler(view_payouts, pattern="^view_payout$"))

    # Edit and delete registrations unchanged...