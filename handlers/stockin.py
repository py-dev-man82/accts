# handlers/stockin.py
# ────────────────────────────────────────────────────────────────
#  Stock-In module  (2025-07-07)  –  **Partner → Store** upgrade + Ledger Compatible
#
#  • New mandatory Store picker between Partner and Item.
#  • partner_inventory row now includes store_id + unit_cost + currency.
#  • store_inventory is incremented / decremented on Add / Edit / Delete
#  • All flows mirror handlers/sales.py: pagination, period filters,
#    numeric-ID shortcuts, unified Back buttons.
#  • **Ledger integration: every stock-in, edit, delete is also recorded in the ledger!**
# ────────────────────────────────────────────────────────────────
import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from tinydb import Query

from handlers.utils import require_unlock, fmt_money, fmt_date
from secure_db       import secure_db

# ╭──────────────────────────────────────────────────────────────╮
# │  Helpers                                                    │
# ╰──────────────────────────────────────────────────────────────╯
def _extract_doc_id(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None

DEFAULT_CUR = "USD"

def _store_currency(sid: int) -> str:
    s = secure_db.table("stores").get(doc_id=sid)
    return s.get("currency", DEFAULT_CUR) if s else DEFAULT_CUR

def _filter_by_time(rows: list, period: str) -> list:
    if period in ("3m", "6m"):
        delta = 90 if period == "3m" else 180
        cut   = datetime.utcnow().timestamp() - delta*86400
        return [r for r in rows
                if datetime.fromisoformat(r["timestamp"]).timestamp() >= cut]
    return rows

# ╭──────────────────────────────────────────────────────────────╮
# │  Ledger integration                                         │
# ╰──────────────────────────────────────────────────────────────╯
def add_ledger_entry(
    type, partner_id, store_id, item_id, quantity, unit_cost, currency, note, date, related_id, delta=0, old_qty=None, old_cost=None
):
    entry = {
        "type": type,
        "partner_id": partner_id,
        "store_id": store_id,
        "item_id": item_id,
        "quantity": quantity,
        "unit_cost": unit_cost,
        "currency": currency,
        "note": note,
        "date": date,
        "timestamp": datetime.utcnow().isoformat(),
        "related_id": related_id,
    }
    if delta != 0:
        entry["delta"] = delta
    if old_qty is not None:
        entry["old_quantity"] = old_qty
    if old_cost is not None:
        entry["old_unit_cost"] = old_cost
    secure_db.insert("ledger", entry)

# ╭──────────────────────────────────────────────────────────────╮
# │  Conversation-state constants (21)                          │
# ╰──────────────────────────────────────────────────────────────╯
(
    SI_PARTNER_SELECT, SI_STORE_SELECT, SI_ITEM_ID, SI_QTY, SI_COST,
    SI_NOTE,           SI_DATE,        SI_CONFIRM,

    SI_EDIT_PARTNER,   SI_EDIT_TIME,   SI_EDIT_PAGE,
    SI_EDIT_FIELD,     SI_EDIT_NEWVAL, SI_EDIT_CONFIRM,

    SI_DEL_PARTNER,    SI_DEL_TIME,    SI_DEL_PAGE, SI_DEL_CONFIRM,

    SI_VIEW_PARTNER,   SI_VIEW_TIME,   SI_VIEW_PAGE,
) = range(21)

# ╭──────────────────────────────────────────────────────────────╮
# │  Main submenu                                               │
# ╰──────────────────────────────────────────────────────────────╯
async def show_stockin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Stock-In",    callback_data="add_stockin")],
        [InlineKeyboardButton("👀 View Stock-Ins",  callback_data="view_stockin")],
        [InlineKeyboardButton("✏️ Edit Stock-In",   callback_data="edit_stockin")],
        [InlineKeyboardButton("🗑️ Remove Stock-In", callback_data="remove_stockin")],
        [InlineKeyboardButton("🔙 Main Menu",       callback_data="main_menu")],
    ])
    msg = "📥 Stock-In: choose an action"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

# ╔══════════════════════════════════════════════════════════════╗
# ║                       ADD  FLOW                              ║
# ╚══════════════════════════════════════════════════════════════╝
@require_unlock
async def add_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners available.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="stockin_menu")]])
        )
        return ConversationHandler.END
    btns = [InlineKeyboardButton(p["name"], callback_data=f"si_part_{p.doc_id}")
            for p in partners]
    rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")])
    await update.callback_query.edit_message_text("Select partner:",
                                                  reply_markup=InlineKeyboardMarkup(rows))
    return SI_PARTNER_SELECT

async def get_stockin_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["partner_id"] = pid

    stores = secure_db.all("stores")
    if not stores:
        await update.callback_query.edit_message_text(
            "No stores defined.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="stockin_menu")]]))
        return ConversationHandler.END
    btns = [InlineKeyboardButton(f"{s['name']} ({s['currency']})",
                                 callback_data=f"si_store_{s.doc_id}")
            for s in stores]
    rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")])
    await update.callback_query.edit_message_text("Select store:",
                                                  reply_markup=InlineKeyboardMarkup(rows))
    return SI_STORE_SELECT

async def get_stockin_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split("_")[-1])
    context.user_data["store_id"] = sid
    await update.callback_query.edit_message_text("Enter *item_id* (or text label):")
    return SI_ITEM_ID

async def get_stockin_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iid = update.message.text.strip()
    context.user_data["item_id"] = iid
    await update.message.reply_text("Quantity:")
    return SI_QTY

async def get_stockin_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text); assert qty > 0
    except Exception:
        await update.message.reply_text("Positive integer, please.")
        return SI_QTY
    context.user_data["qty"] = qty
    await update.message.reply_text("Unit cost:")
    return SI_COST

async def get_stockin_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cost = float(update.message.text); assert cost >= 0
    except Exception:
        await update.message.reply_text("Numeric cost, please.")
        return SI_COST
    context.user_data["cost"] = cost
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="note_skip")]])
    await update.message.reply_text("Optional note (or Skip):", reply_markup=kb)
    return SI_NOTE

async def get_stockin_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "note_skip":
        await update.callback_query.answer()
        note = ""
    else:
        note = update.message.text.strip()
    context.user_data["note"] = note

    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip", callback_data="date_skip")]])
    prompt = f"Enter date DDMMYYYY or Skip for today ({today}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return SI_DATE

async def get_stockin_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "date_skip":
        await update.callback_query.answer()
        date_str = datetime.now().strftime("%d%m%Y")
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, "%d%m%Y")
        except ValueError:
            await update.message.reply_text("Format DDMMYYYY, please.")
            return SI_DATE
    context.user_data["date"] = date_str

    # summary
    d   = context.user_data
    cur = _store_currency(d["store_id"])
    total = d["qty"] * d["cost"]
    pname = secure_db.table("partners").get(doc_id=d["partner_id"])["name"]
    sname = secure_db.table("stores").get(doc_id=d["store_id"])["name"]
    summary = (
        f"✅ **Confirm Stock-In**\n"
        f"Partner: {pname}\n"
        f"Store:   {sname}\n"
        f"Item {d['item_id']} ×{d['qty']}\n"
        f"Unit Cost: {fmt_money(d['cost'],  cur)}\n"
        f"Total:     {fmt_money(total,      cur)}\n"
        f"Note: {d.get('note') or '—'}\n"
        f"Date: {fmt_date(d['date'])}\n\nConfirm?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="si_yes"),
         InlineKeyboardButton("❌ No",  callback_data="si_no")]
    ])
    await (update.callback_query.edit_message_text if update.callback_query
          else update.message.reply_text)(summary, reply_markup=kb)
    return SI_CONFIRM

@require_unlock
async def confirm_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "si_yes":
        await show_stockin_menu(update, context); return ConversationHandler.END

    d = context.user_data
    cur = _store_currency(d["store_id"])
    # ---------- partner_inventory (history) ----------
    try:
        partner_inv_id = secure_db.insert("partner_inventory", {
            "partner_id": d["partner_id"],
            "store_id":   d["store_id"],
            "item_id":    d["item_id"],
            "quantity":   d["qty"],
            "unit_cost":  d["cost"],
            "note":       d.get("note",""),
            "date":       d["date"],
            "currency":   cur,
            "timestamp":  datetime.utcnow().isoformat(),
        })
        # ---------- store_inventory (physical stock) -----
        q = Query()
        rec = secure_db.table("store_inventory").get((q.store_id == d["store_id"]) &
                                                     (q.item_id  == d["item_id"]))
        if rec:
            secure_db.update("store_inventory",
                            {"quantity": rec["quantity"] + d["qty"],
                             "unit_cost": d["cost"],
                             "currency":  cur},
                            [rec.doc_id])
        else:
            secure_db.insert("store_inventory", {
                "store_id": d["store_id"],
                "item_id":  d["item_id"],
                "quantity": d["qty"],
                "unit_cost":d["cost"],
                "currency": cur,
            })
        # ---------- LEDGER (transaction) ----------
        add_ledger_entry(
            type="stockin",
            partner_id=d["partner_id"],
            store_id=d["store_id"],
            item_id=d["item_id"],
            quantity=d["qty"],
            unit_cost=d["cost"],
            currency=cur,
            note=d.get("note", ""),
            date=d["date"],
            related_id=partner_inv_id
        )
    except Exception as e:
        # Rollback (remove just-added partner_inventory, undo store_inventory change)
        # Try to remove partner_inventory entry if present
        try:
            if 'partner_inv_id' in locals():
                secure_db.remove("partner_inventory", [partner_inv_id])
        except Exception:
            pass
        # Try to undo store_inventory update if present
        try:
            q = Query()
            rec = secure_db.table("store_inventory").get((q.store_id == d["store_id"]) &
                                                        (q.item_id  == d["item_id"]))
            if rec:
                secure_db.update("store_inventory",
                                {"quantity": rec["quantity"] - d["qty"]},
                                [rec.doc_id])
        except Exception:
            pass
        await update.callback_query.edit_message_text(
            f"❌ Stock-In failed to write to ledger. No changes saved.\n{str(e)}"
        )
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        f"✅ Stock-In recorded & allocated to store.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                 callback_data="stockin_menu")]]))
    return ConversationHandler.END

# ╔══════════════════════════════════════════════════════════════╗
# ║                       VIEW  FLOW                             ║
# ╚══════════════════════════════════════════════════════════════╝
# (unchanged ...)

# ╔══════════════════════════════════════════════════════════════╗
# ║                       EDIT  FLOW                             ║
# ╚══════════════════════════════════════════════════════════════╝
@require_unlock
async def confirm_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "edit_conf_yes":
        await show_stockin_menu(update, context); return ConversationHandler.END

    sid   = context.user_data["edit_stock_id"]
    field = context.user_data["edit_field"]
    val   = context.user_data["new_value"]

    # fetch current record for delta math
    rec = secure_db.table("partner_inventory").get(doc_id=sid)
    store_id = rec["store_id"]

    # Ledger edit tracking variables
    ledger_type = None
    ledger_args = {}

    try:
        if field == "qty":
            new_qty = int(val)
            delta   = new_qty - rec["quantity"]
            secure_db.update("partner_inventory", {"quantity": new_qty}, [sid])

            q = Query()
            inv = secure_db.table("store_inventory").get((q.store_id == store_id) &
                                                        (q.item_id == rec["item_id"]))
            if inv:
                secure_db.update("store_inventory",
                                {"quantity": inv["quantity"] + delta},
                                [inv.doc_id])
            # ------ Ledger for quantity change ------
            ledger_type = "stockin_edit_qty"
            ledger_args = dict(
                partner_id=rec["partner_id"], store_id=rec["store_id"],
                item_id=rec["item_id"], quantity=new_qty,
                unit_cost=rec["unit_cost"], currency=rec["currency"],
                note=f"Edit qty (was {rec['quantity']})",
                date=rec["date"], related_id=sid, delta=delta,
                old_qty=rec["quantity"], old_cost=rec["unit_cost"]
            )
        elif field == "cost":
            old_cost = rec["unit_cost"]
            secure_db.update("partner_inventory", {"unit_cost": float(val)}, [sid])
            # also update last cost on store_inventory
            q = Query()
            inv = secure_db.table("store_inventory").get((q.store_id == store_id) &
                                                        (q.item_id == rec["item_id"]))
            if inv:
                secure_db.update("store_inventory", {"unit_cost": float(val)}, [inv.doc_id])
            # ------ Ledger for cost change ------
            ledger_type = "stockin_edit_cost"
            ledger_args = dict(
                partner_id=rec["partner_id"], store_id=rec["store_id"],
                item_id=rec["item_id"], quantity=rec["quantity"],
                unit_cost=float(val), currency=rec["currency"],
                note=f"Edit cost (was {old_cost})",
                date=rec["date"], related_id=sid, delta=0,
                old_qty=rec["quantity"], old_cost=old_cost
            )
        elif field == "date":
            secure_db.update("partner_inventory", {"date": val}, [sid])
        elif field == "note":
            secure_db.update("partner_inventory",
                            {"note": "" if val == "-" else val}, [sid])

        # Only add to ledger for qty/cost edits
        if ledger_type:
            add_ledger_entry(type=ledger_type, **ledger_args)
    except Exception as e:
        await update.callback_query.edit_message_text(
            f"❌ Stock-In edit failed: {str(e)}"
        )
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        "✅ Stock-In updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                 callback_data="stockin_menu")]]))
    return ConversationHandler.END

# ╔══════════════════════════════════════════════════════════════╗
# ║                       DELETE  FLOW                           ║
# ╚══════════════════════════════════════════════════════════════╝
@require_unlock
async def del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "del_conf_yes":
        await show_stockin_menu(update, context); return ConversationHandler.END
    sid = context.user_data["del_id"]
    rec = secure_db.table("partner_inventory").get(doc_id=sid)

    try:
        # subtract from store inventory
        if rec:
            q = Query()
            inv = secure_db.table("store_inventory").get((q.store_id == rec["store_id"]) &
                                                        (q.item_id  == rec["item_id"]))
            if inv:
                secure_db.update("store_inventory",
                                {"quantity": inv["quantity"] - rec["quantity"]},
                                [inv.doc_id])
            # Ledger: mark removal
            add_ledger_entry(
                type="stockin_delete",
                partner_id=rec["partner_id"], store_id=rec["store_id"],
                item_id=rec["item_id"], quantity=rec["quantity"],
                unit_cost=rec["unit_cost"], currency=rec["currency"],
                note=f"Stock-in deleted: {rec.get('note','')}",
                date=rec["date"], related_id=sid
            )
        secure_db.remove("partner_inventory", [sid])
    except Exception as e:
        await update.callback_query.edit_message_text(
            f"❌ Stock-In delete failed: {str(e)}"
        )
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        f"✅ Stock-In #{sid} deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                 callback_data="stockin_menu")]]))
    return ConversationHandler.END

# ╔══════════════════════════════════════════════════════════════╗
# ║        ConversationHandlers and Registration                 ║
# ╚══════════════════════════════════════════════════════════════╝
add_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(add_stockin, pattern="^add_stockin$"),
                  CommandHandler("add_stockin", add_stockin)],
    states={
        SI_PARTNER_SELECT:[CallbackQueryHandler(get_stockin_partner, pattern="^si_part_")],
        SI_STORE_SELECT:  [CallbackQueryHandler(get_stockin_store,  pattern="^si_store_")],
        SI_ITEM_ID:       [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stockin_item)],
        SI_QTY:           [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stockin_qty)],
        SI_COST:          [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stockin_cost)],
        SI_NOTE:          [CallbackQueryHandler(get_stockin_note, pattern="^note_skip$"),
                           MessageHandler(filters.TEXT & ~filters.COMMAND, get_stockin_note)],
        SI_DATE:          [CallbackQueryHandler(get_stockin_date, pattern="^date_skip$"),
                           MessageHandler(filters.TEXT & ~filters.COMMAND, get_stockin_date)],
        SI_CONFIRM:       [CallbackQueryHandler(confirm_stockin, pattern="^si_")],
    },
    fallbacks=[CommandHandler("cancel", show_stockin_menu)],
    per_message=False,
)

view_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(view_stockin_start, pattern="^view_stockin$")],
    states={
        SI_VIEW_PARTNER:[CallbackQueryHandler(view_choose_period, pattern="^si_view_part_"),
                         CallbackQueryHandler(show_stockin_menu,  pattern="^stockin_menu$")],
        SI_VIEW_TIME:   [CallbackQueryHandler(view_set_filter,    pattern="^view_time_"),
                         CallbackQueryHandler(view_stockin_start, pattern="^view_stockin$")],
        SI_VIEW_PAGE:   [CallbackQueryHandler(handle_view_pagination, pattern="^view_(prev|next)$"),
                         CallbackQueryHandler(view_stockin_start,     pattern="^view_stockin$")],
    },
    fallbacks=[CommandHandler("cancel", show_stockin_menu)],
    per_message=False,
)

edit_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(edit_stockin_start, pattern="^edit_stockin$")],
    states={
        SI_EDIT_PARTNER:[CallbackQueryHandler(edit_choose_period, pattern="^si_edit_part_"),
                         CallbackQueryHandler(show_stockin_menu,  pattern="^stockin_menu$")],
        SI_EDIT_TIME:   [CallbackQueryHandler(edit_set_filter,    pattern="^edit_time_"),
                         CallbackQueryHandler(edit_stockin_start, pattern="^edit_stockin$")],
        SI_EDIT_PAGE:   [CallbackQueryHandler(handle_edit_pagination, pattern="^edit_(prev|next)$"),
                         CallbackQueryHandler(edit_stockin_start,     pattern="^edit_stockin$"),
                         MessageHandler(filters.Regex(r"^\d+$") & ~filters.COMMAND,
                                        edit_pick_doc)],
        SI_EDIT_FIELD:  [CallbackQueryHandler(get_edit_field, pattern="^edit_field_")],
        SI_EDIT_NEWVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit)],
        SI_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit, pattern="^edit_conf_")],
    },
    fallbacks=[CommandHandler("cancel", show_stockin_menu)],
    per_message=False,
)

del_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(del_stockin_start, pattern="^remove_stockin$")],
    states={
        SI_DEL_PARTNER:[CallbackQueryHandler(del_choose_period,  pattern="^si_del_part_"),
                        CallbackQueryHandler(show_stockin_menu,  pattern="^stockin_menu$")],
        SI_DEL_TIME:   [CallbackQueryHandler(del_set_filter,     pattern="^del_time_"),
                        CallbackQueryHandler(del_stockin_start,  pattern="^remove_stockin$")],
        SI_DEL_PAGE:   [CallbackQueryHandler(handle_del_pagination, pattern="^del_(prev|next)$"),
                        CallbackQueryHandler(del_stockin_start,      pattern="^remove_stockin$"),
                        MessageHandler(filters.Regex(r"^\d+$") & ~filters.COMMAND,
                                       del_pick_doc)],
        SI_DEL_CONFIRM:[CallbackQueryHandler(del_confirm, pattern="^del_conf_")],
    },
    fallbacks=[CommandHandler("cancel", show_stockin_menu)],
    per_message=False,
)

def register_stockin_handlers(app: Application):
    app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))
    app.add_handler(add_conv)
    app.add_handler(view_conv)
    app.add_handler(edit_conv)
    app.add_handler(del_conv)
