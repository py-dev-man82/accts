# handlers/owner.py
import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from secure_db import secure_db
from handlers.utils import require_unlock
from handlers.ledger import add_ledger_entry, get_balance

(
    O_POT_ACTION,
    O_POT_INPUT,
    O_POT_NOTE,
    O_POT_CONFIRM,
) = range(4)

# ────────────────────────────────────────────────
# Owner Main Menu (POT only)
# ────────────────────────────────────────────────
async def show_owner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏦 Adjust POT Balance",callback_data="owner_adjust_pot")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ]
    )
    await update.callback_query.edit_message_text("👑 Owner: choose an action", reply_markup=kb)

# ════════════════════════════════════════════════
# Adjust POT Balance flow (all in ledger)
# ════════════════════════════════════════════════
@require_unlock
async def adjust_pot_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pot_balance = get_balance("owner", "POT")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Funds",callback_data="pot_add"),
         InlineKeyboardButton("➖ Subtract Funds",callback_data="pot_subtract")],
        [InlineKeyboardButton("✏️ Set Exact Balance",callback_data="pot_set")],
        [InlineKeyboardButton("🔙 Back",callback_data="owner_menu")],
    ])
    await update.callback_query.edit_message_text(
        f"🏦 Current POT Balance: ${pot_balance:,.2f}\n\nChoose:", reply_markup=kb)
    return O_POT_ACTION

async def get_pot_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["pot_action"]=update.callback_query.data  # pot_add|pot_subtract|pot_set
    prompt={"pot_add":"Enter amount to add:",
            "pot_subtract":"Enter amount to subtract:",
            "pot_set":"Enter new POT balance:"}[update.callback_query.data]
    await update.callback_query.edit_message_text(prompt)
    return O_POT_INPUT

async def get_pot_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text.strip())
    except:
        await update.message.reply_text("Enter a valid number:")
        return O_POT_INPUT

    context.user_data["pot_amount"] = amt
    # For pot_set, store the current balance
    if context.user_data["pot_action"] == "pot_set":
        context.user_data["pot_old_balance"] = get_balance("owner", "POT")
    await update.message.reply_text("Enter a note for this adjustment (or skip):")
    return O_POT_NOTE

async def confirm_pot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    context.user_data["pot_note"] = note
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm",callback_data="pot_conf_yes"),
         InlineKeyboardButton("❌ Cancel",callback_data="pot_conf_no")]
    ])
    amt = context.user_data["pot_amount"]
    action = context.user_data["pot_action"]
    if action == "pot_set":
        old = context.user_data.get("pot_old_balance", 0.0)
        diff = amt - old
        txt = f"Set POT balance from ${old:,.2f} to ${amt:,.2f}?\n(Change: {diff:+.2f})"
    else:
        txt = f"{'Add' if action=='pot_add' else 'Subtract'} ${amt:,.2f} to POT?"
    if note:
        txt += f"\nNote: {note}"
    await update.message.reply_text(txt, reply_markup=kb)
    return O_POT_CONFIRM

@require_unlock
async def save_pot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "pot_conf_yes":
        await show_owner_menu(update, context)
        return ConversationHandler.END

    action = context.user_data["pot_action"]
    amt    = context.user_data["pot_amount"]
    note   = context.user_data.get("pot_note","")
    if action == "pot_set":
        old = context.user_data.get("pot_old_balance", 0.0)
        adj = amt - old
    elif action == "pot_add":
        adj = amt
    elif action == "pot_subtract":
        adj = -amt
    else:
        await show_owner_menu(update, context)
        return ConversationHandler.END

    add_ledger_entry(
        account_type="owner",
        account_id="POT",
        entry_type="pot_adjustment",
        related_id=None,
        amount=adj,
        currency="USD",
        note=note,
        date=datetime.utcnow().strftime("%d%m%Y"),
        timestamp=datetime.utcnow().isoformat(),
    )
    await update.callback_query.edit_message_text(
        "✅ POT adjustment recorded.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="owner_menu")]])
    )
    return ConversationHandler.END

def register_owner_handlers(app):
    app.add_handler(CallbackQueryHandler(show_owner_menu, pattern="^owner_menu$"))
    app.add_handler(CallbackQueryHandler(adjust_pot_balance, pattern="^owner_adjust_pot$"))
    app.add_handler(CallbackQueryHandler(get_pot_amount, pattern="^pot_add|^pot_subtract|^pot_set$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_pot_note))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_pot))
    app.add_handler(CallbackQueryHandler(save_pot, pattern="^pot_conf_yes|^pot_conf_no$"))
