# handlers/stockin.py  (Part 1 – Add flow + submenu)

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


# ────────────────────────────────────────────────────────────
#  Conversation-state constants
# ────────────────────────────────────────────────────────────
(
    SI_PARTNER_SELECT,
    SI_ITEM_SELECT,
    SI_QTY,
    SI_COST,
    SI_NOTE,
    SI_DATE,
    SI_CONFIRM,
    SI_EDIT_SELECT,
    SI_EDIT_FIELD,
    SI_EDIT_NEWVAL,
    SI_EDIT_CONFIRM,
    SI_DELETE_SELECT,
    SI_DELETE_CONFIRM,
) = range(13)


# ────────────────────────────────────────────────────────────
#  Sub-menu
# ────────────────────────────────────────────────────────────
async def show_stockin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Stock-In",    callback_data="add_stockin")],
        [InlineKeyboardButton("👀 View Stock-Ins",  callback_data="view_stockin")],
        [InlineKeyboardButton("✏️ Edit Stock-In",   callback_data="edit_stockin")],
        [InlineKeyboardButton("🗑️ Remove Stock-In", callback_data="remove_stockin")],
        [InlineKeyboardButton("🔙 Main Menu",       callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text("Stock-In: choose an action", reply_markup=kb)


# ======================================================================
#                                ADD  FLOW
# ======================================================================
@require_unlock
async def add_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners available.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(p["name"], callback_data=f"si_part_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i + 2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a partner:", reply_markup=kb)
    return SI_PARTNER_SELECT


async def get_stockin_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["partner_id"] = int(update.callback_query.data.split("_")[-1])

    items = secure_db.all("items")
    if not items:
        await update.callback_query.edit_message_text(
            "No items available.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(i["name"], callback_data=f"si_item_{i.doc_id}") for i in items]
    kb = InlineKeyboardMarkup([buttons[i:i + 2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select an item:", reply_markup=kb)
    return SI_ITEM_SELECT


async def get_stockin_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["item_id"] = int(update.callback_query.data.split("_")[-1])
    await update.callback_query.edit_message_text("Enter quantity (integer):")
    return SI_QTY


async def get_stockin_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        assert qty > 0
    except Exception:
        await update.message.reply_text("Enter a positive integer.")
        return SI_QTY
    context.user_data["qty"] = qty
    await update.message.reply_text("Enter cost per unit (e.g. 12.50):")
    return SI_COST


async def get_stockin_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cost = float(update.message.text.strip())
    except Exception:
        await update.message.reply_text("Enter a valid number.")
        return SI_COST
    context.user_data["cost"] = cost
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="si_note_skip")]])
    await update.message.reply_text("Enter an optional note or press Skip:", reply_markup=kb)
    return SI_NOTE


async def get_stockin_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        note = ""
    else:
        note = update.message.text.strip()
    context.user_data["note"] = note

    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="si_date_skip")]])
    prompt = f"Enter stock-in date DDMMYYYY or press Skip for today ({today}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return SI_DATE


async def get_stockin_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date_str = datetime.now().strftime("%d%m%Y")
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, "%d%m%Y")
        except ValueError:
            await update.message.reply_text("Format DDMMYYYY please.")
            return SI_DATE
    context.user_data["date"] = date_str
    return await confirm_stockin_prompt(update, context)


async def confirm_stockin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    summary = (
        f"Partner: {d['partner_id']}\n"
        f"Item:    {d['item_id']}\n"
        f"Qty:     {d['qty']}\n"
        f"Cost:    {d['cost']:.2f}\n"
        f"Note:    {d.get('note') or '—'}\n"
        f"Date:    {d['date']}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data="si_conf_yes"),
        InlineKeyboardButton("❌ Cancel",  callback_data="si_conf_no"),
    ]])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return SI_CONFIRM


@require_unlock
async def confirm_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "si_conf_yes":
        await show_stockin_menu(update, context)
        return ConversationHandler.END

    d = context.user_data
    secure_db.insert("partner_inventory", {
        "partner_id": d["partner_id"],
        "item_id":    d["item_id"],
        "quantity":   d["qty"],
        "cost":       d["cost"],
        "note":       d.get("note", ""),
        "date":       d["date"],
        "timestamp":  datetime.utcnow().isoformat(),
    })
    await update.callback_query.edit_message_text(
        "✅ Stock-In recorded.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]])
    )
    return ConversationHandler.END


# handlers/stockin.py  (Part 2 – View, Edit, Delete & handler registration)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from datetime import datetime
from handlers.utils import require_unlock
from secure_db import secure_db

# (state constants & earlier functions are defined in Part 1)

# ======================================================================
#                                VIEW  FLOW
# ======================================================================
@require_unlock
async def view_stockins(update, context):
    await update.callback_query.answer()
    rows = secure_db.all("partner_inventory")
    if not rows:
        text = "No stock-in records found."
    else:
        lines = []
        for r in rows:
            partner = secure_db.table("partners").get(doc_id=r["partner_id"])
            item    = secure_db.table("items").get(doc_id=r["item_id"])
            pname   = partner["name"] if partner else "Unknown"
            iname   = item["name"] if item else "Unknown"
            lines.append(f"[{r.doc_id}] {pname}: {iname} x{r['quantity']} @ {r['cost']:.2f} "
                         f"on {r.get('date','')} | Note: {r.get('note','')}")
        text = "Stock-Ins:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)


# ======================================================================
#                                EDIT  FLOW
# ======================================================================
@require_unlock
async def edit_stockin(update, context):
    await update.callback_query.answer()
    rows = secure_db.all("partner_inventory")
    if not rows:
        await update.callback_query.edit_message_text(
            "No stock-in records to edit.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['quantity']} @ {r['cost']}",
                                    callback_data=f"edit_stockin_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i + 2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a stock-in to edit:", reply_markup=kb)
    return SI_EDIT_SELECT


async def get_edit_selection(update, context):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split("_")[-1])
    rec = secure_db.table("partner_inventory").get(doc_id=sid)
    context.user_data.update({
        "edit_id":   sid,
        "partner_id": rec["partner_id"],
        "item_id":    rec["item_id"],
        "quantity":   rec["quantity"],
        "cost":       rec["cost"],
        "note":       rec.get("note", ""),
        "date":       rec.get("date", datetime.now().strftime("%d%m%Y")),
    })
    await update.callback_query.edit_message_text("Enter new quantity:")
    return SI_EDIT_FIELD


async def get_edit_field(update, context):
    try:
        qty = int(update.message.text.strip())
        assert qty > 0
    except Exception:
        await update.message.reply_text("Enter a positive integer.")
        return SI_EDIT_FIELD
    context.user_data["quantity"] = qty
    await update.message.reply_text("Enter new cost per unit:")
    return SI_EDIT_NEWVAL


async def get_edit_newval(update, context):
    try:
        cost = float(update.message.text.strip())
    except Exception:
        await update.message.reply_text("Enter a valid number.")
        return SI_EDIT_NEWVAL
    context.user_data["cost"] = cost

    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="edate_skip")]])
    prompt = f"Enter new stock-in date DDMMYYYY or press Skip for today ({today}):"
    await update.message.reply_text(prompt, reply_markup=kb)
    return SI_EDIT_CONFIRM


async def get_edit_date(update, context):
    if update.callback_query:
        await update.callback_query.answer()
        date_str = datetime.now().strftime("%d%m%Y")
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, "%d%m%Y")
        except ValueError:
            await update.message.reply_text("Format DDMMYYYY please.")
            return SI_EDIT_CONFIRM
    context.user_data["date"] = date_str

    d = context.user_data
    summary = (
        f"Partner: {d['partner_id']}\n"
        f"Item:    {d['item_id']}\n"
        f"Qty:     {d['quantity']}\n"
        f"Cost:    {d['cost']:.2f}\n"
        f"Date:    {d['date']}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Save", callback_data="edit_conf_yes"),
        InlineKeyboardButton("❌ Cancel", callback_data="edit_conf_no"),
    ]])
    await update.message.reply_text(summary, reply_markup=kb)
    return SI_EDIT_CONFIRM


@require_unlock
async def confirm_edit_stockin(update, context):
    await update.callback_query.answer()
    if update.callback_query.data != "edit_conf_yes":
        await show_stockin_menu(update, context)
        return ConversationHandler.END

    d = context.user_data
    secure_db.update("partner_inventory", {
        "quantity": d["quantity"],
        "cost":     d["cost"],
        "date":     d["date"],
    }, [d["edit_id"]])
    await update.callback_query.edit_message_text(
        "✅ Stock-In record updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]])
    )
    return ConversationHandler.END


# ======================================================================
#                               DELETE FLOW
# ======================================================================
@require_unlock
async def remove_stockin(update, context):
    await update.callback_query.answer()
    rows = secure_db.all("partner_inventory")
    if not rows:
        await update.callback_query.edit_message_text(
            "No stock-in records to remove.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['quantity']} @ {r['cost']}",
                                    callback_data=f"del_stockin_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i + 2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a stock-in to remove:", reply_markup=kb)
    return SI_DELETE_SELECT


@require_unlock
async def confirm_delete_stockin(update, context):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split("_")[-1])
    secure_db.remove("partner_inventory", [sid])
    await update.callback_query.edit_message_text(
        "✅ Stock-In record deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]])
    )
    return ConversationHandler.END


# ======================================================================
#                       REGISTER  HANDLERS
# ======================================================================
def register_stockin_handlers(app):
    app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))

    # Add
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_stockin", add_stockin),
            CallbackQueryHandler(add_stockin, pattern="^add_stockin$")
        ],
        states={
            SI_PARTNER_SELECT: [CallbackQueryHandler(get_stockin_partner, pattern="^si_part_\\d+$")],
            SI_ITEM_SELECT:    [CallbackQueryHandler(get_stockin_item,   pattern="^si_item_\\d+$")],
            SI_QTY:            [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stockin_qty)],
            SI_COST:           [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stockin_cost)],
            SI_NOTE:           [CallbackQueryHandler(get_stockin_note,  pattern="^si_note_skip$"),
                                MessageHandler(filters.TEXT & ~filters.COMMAND, get_stockin_note)],
            SI_DATE:           [CallbackQueryHandler(get_stockin_date,  pattern="^si_date_skip$"),
                                MessageHandler(filters.TEXT & ~filters.COMMAND, get_stockin_date)],
            SI_CONFIRM:        [CallbackQueryHandler(confirm_stockin,   pattern="^si_conf_")],
        },
        fallbacks=[CommandHandler("cancel", show_stockin_menu)],
        per_message=False,
    )
    app.add_handler(add_conv)

    # View
    app.add_handler(CallbackQueryHandler(view_stockins, pattern="^view_stockin$"))

    # Edit
    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_stockin", edit_stockin),
            CallbackQueryHandler(edit_stockin, pattern="^edit_stockin$")
        ],
        states={
            SI_EDIT_SELECT:  [CallbackQueryHandler(get_edit_selection, pattern="^edit_stockin_\\d+$")],
            SI_EDIT_FIELD:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_field)],
            SI_EDIT_NEWVAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_newval)],
            SI_EDIT_CONFIRM: [CallbackQueryHandler(confirm_edit_stockin,      pattern="^edit_conf_")],
        },
        fallbacks=[CommandHandler("cancel", show_stockin_menu)],
        per_message=False,
    )
    app.add_handler(edit_conv)

    # Delete
    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("remove_stockin", remove_stockin),
            CallbackQueryHandler(remove_stockin, pattern="^remove_stockin$")
        ],
        states={
            SI_DELETE_SELECT: [CallbackQueryHandler(confirm_delete_stockin, pattern="^del_stockin_\\d+$")],
        },
        fallbacks=[CommandHandler("cancel", show_stockin_menu)],
        per_message=False,
    )
    app.add_handler(del_conv)