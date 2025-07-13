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
    CommandHandler,
    Application,
)
from secure_db import secure_db
from handlers.utils import require_unlock
from handlers.ledger import add_ledger_entry, get_balance

# --- Import backup/restore actions from your backup module ---
from handlers.backup import (
    backup_command,
    backups_command,
    restore_command,
)

(
    O_POT_ACTION,
    O_POT_INPUT,
    O_POT_NOTE,
    O_POT_CONFIRM,
) = range(4)

# ────────────────────────────────────────────────
# Owner Main Menu (with Backup/Restore)
# ────────────────────────────────────────────────
async def show_owner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] Entered show_owner_menu")
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏦 Adjust POT Balance", callback_data="owner_adjust_pot")],
        [InlineKeyboardButton("🛡️ Backup/Restore", callback_data="backup_menu")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text("👑 Owner: choose an action", reply_markup=kb)

# ────────────────────────────────────────────────
# Backup/Restore Submenu
# ────────────────────────────────────────────────
async def show_backup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] Entered show_backup_menu")
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗄️ Backup Now", callback_data="backup_now")],
        [InlineKeyboardButton("🗄️ Restore Server Backup", callback_data="backup_list")],
        [InlineKeyboardButton("♻️ Restore From File", callback_data="backup_restore")],
        [InlineKeyboardButton("🔙 Back", callback_data="owner_menu")],
    ])
    await update.callback_query.edit_message_text(
        "🛡️ Backup & Restore:\nChoose an action.", reply_markup=kb
    )

# --- Handle Backup/Restore submenu button clicks ---
async def handle_backup_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] Entered handle_backup_menu_button, data:", update.callback_query.data)
    data = update.callback_query.data
    if data == "backup_now":
        print("[DEBUG] Calling backup_command")
        await backup_command(update, context)
    elif data == "backup_list":
        print("[DEBUG] Calling backups_command")
        await backups_command(update, context)
    elif data == "backup_restore":
        print("[DEBUG] Calling restore_command")
        await restore_command(update, context)
    else:
        print("[DEBUG] Unknown backup menu button:", data)
        await update.callback_query.answer("Unknown action.", show_alert=True)

# ════════════════════════════════════════════════
# Adjust POT Balance flow (multi-step, ConversationHandler)
# ════════════════════════════════════════════════
@require_unlock
async def adjust_pot_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] Entered adjust_pot_balance")
    if hasattr(update, "callback_query") and update.callback_query:
        await update.callback_query.answer()
        msg_method = update.callback_query.edit_message_text
    else:
        msg_method = update.message.reply_text

    pot_balance = get_balance("owner", "POT")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Funds", callback_data="pot_add"),
         InlineKeyboardButton("➖ Subtract Funds", callback_data="pot_subtract")],
        [InlineKeyboardButton("✏️ Set Exact Balance", callback_data="pot_set")],
        [InlineKeyboardButton("🔙 Back", callback_data="owner_menu")],
    ])
    await msg_method(
        f"🏦 Current POT Balance: ${pot_balance:,.2f}\n\nChoose:", reply_markup=kb)
    return O_POT_ACTION

async def get_pot_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] Entered get_pot_amount, data:", update.callback_query.data)
    await update.callback_query.answer()
    context.user_data["pot_action"] = update.callback_query.data  # pot_add|pot_subtract|pot_set
    prompt = {
        "pot_add": "Enter amount to add:",
        "pot_subtract": "Enter amount to subtract:",
        "pot_set": "Enter new POT balance:"
    }[update.callback_query.data]
    await update.callback_query.edit_message_text(prompt)
    # Reset in case someone was halfway through a previous flow
    context.user_data.pop("pot_amount", None)
    context.user_data.pop("pot_note", None)
    context.user_data.pop("pot_old_balance", None)
    return O_POT_INPUT

@require_unlock
async def get_pot_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] Entered get_pot_note. Current state:", context.user_data)
    # If we don't have an amount yet, expect number input here
    if "pot_amount" not in context.user_data:
        try:
            amt = float(update.message.text.strip())
            print(f"[DEBUG] Received amount: {amt}")
        except:
            print("[DEBUG] Invalid number entered")
            await update.message.reply_text("Enter a valid number:")
            return O_POT_INPUT

        context.user_data["pot_amount"] = amt
        # For pot_set, store the current balance
        if context.user_data.get("pot_action") == "pot_set":
            context.user_data["pot_old_balance"] = get_balance("owner", "POT")
        await update.message.reply_text("Enter a note for this adjustment (or skip):")
        return O_POT_NOTE

    # Else, this is the note input step
    note = update.message.text.strip()
    context.user_data["pot_note"] = note
    print(f"[DEBUG] Note entered: {note}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="pot_conf_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="pot_conf_no")]
    ])
    amt = context.user_data["pot_amount"]
    action = context.user_data["pot_action"]
    if action == "pot_set":
        old = context.user_data.get("pot_old_balance", 0.0)
        diff = amt - old
        txt = f"Set POT balance from ${old:,.2f} to ${amt:,.2f}?\n(Change: {diff:+.2f})"
    else:
        txt = f"{'Add' if action == 'pot_add' else 'Subtract'} ${amt:,.2f} to POT?"
    if note:
        txt += f"\nNote: {note}"
    await update.message.reply_text(txt, reply_markup=kb)
    return O_POT_CONFIRM

@require_unlock
async def save_pot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] Entered save_pot, data:", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data != "pot_conf_yes":
        print("[DEBUG] POT flow cancelled")
        await show_owner_menu(update, context)
        return ConversationHandler.END

    action = context.user_data.get("pot_action")
    amt = context.user_data.get("pot_amount", 0.0)
    note = context.user_data.get("pot_note", "")
    print(f"[DEBUG] Finalizing POT: action={action}, amt={amt}, note={note}")
    if action == "pot_set":
        old = context.user_data.get("pot_old_balance", 0.0)
        adj = amt - old
    elif action == "pot_add":
        adj = amt
    elif action == "pot_subtract":
        adj = -amt
    else:
        print("[DEBUG] Unknown POT action")
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
    # Clean up so another flow can start fresh if desired
    context.user_data.pop("pot_action", None)
    context.user_data.pop("pot_amount", None)
    context.user_data.pop("pot_note", None)
    context.user_data.pop("pot_old_balance", None)
    return ConversationHandler.END

# --- Debug catch-all handler (ALWAYS last) ---
async def debug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("\n[DEBUG] Callback data received (not matched by any handler):", getattr(update.callback_query, "data", None))
    if hasattr(update, "callback_query") and update.callback_query:
        print("[DEBUG] CallbackQuery user:", update.callback_query.from_user.id)
        print("[DEBUG] CallbackQuery message_id:", update.callback_query.message.message_id)
    await update.callback_query.answer("Debug: Button pressed", show_alert=True)

# --- Registration for all owner menu logic, including nested backup/restore ---
def register_owner_handlers(app: Application):
    print("[DEBUG] Registering all owner handlers")
    # Adjust POT: ConversationHandler with BOTH /adjustpot and button entry
    pot_conv = ConversationHandler(
        entry_points=[ 
            CallbackQueryHandler(adjust_pot_balance, pattern="^owner_adjust_pot$"),
            CommandHandler("adjustpot", adjust_pot_balance),
        ],
        states={
            O_POT_ACTION: [CallbackQueryHandler(get_pot_amount, pattern="^pot_add$|^pot_subtract$|^pot_set$")],
            O_POT_INPUT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pot_note)],
            O_POT_NOTE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pot_note)],
            O_POT_CONFIRM:[CallbackQueryHandler(save_pot, pattern="^pot_conf_yes$|^pot_conf_no$")]
        },
        fallbacks=[CallbackQueryHandler(show_owner_menu, pattern="^owner_menu$")],
        name="pot_conv"
    )
    app.add_handler(pot_conv)

    # Owner menu and backup/restore handlers (all work from both button and command)
    app.add_handler(CallbackQueryHandler(show_owner_menu, pattern="^owner_menu$"))
    app.add_handler(CallbackQueryHandler(show_backup_menu, pattern="^backup_menu$"))
    app.add_handler(CallbackQueryHandler(handle_backup_menu_button, pattern="^(backup_now|backup_list|backup_restore)$"))

    # Register direct commands for backup actions if you want them too:
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("backups", backups_command))
    app.add_handler(CommandHandler("restore", restore_command))

    # Register the debug handler LAST
    app.add_handler(CallbackQueryHandler(debug_callback))
