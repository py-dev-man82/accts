# handlers/stockin.py
# ────────────────────────────────────────────────────────────────
#  Stock-In module  (2025-07-07)  –  **Partner → Store** upgrade + Ledger Compatible
#  • Mandatory Store picker between Partner and Item.
#  • partner_inventory row includes store_id + unit_cost + currency
#  • store_inventory incremented / decremented on Add / Edit / Delete
#  • All flows mirror handlers/sales.py: pagination, period filters, Back btns.
#  • Ledger integration: every stock-in, edit, delete is also recorded in the ledger!
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
from handlers.ledger import add_ledger_entry

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

def _format_stockin_row(r):
    try:
        dt = datetime.fromisoformat(r["timestamp"])
    except Exception:
        dt = datetime.strptime(r.get("timestamp", ""), "%Y-%m-%dT%H:%M:%S.%f")
    date = dt.strftime("%d/%m/%y")
    item = r["item_id"]
    qty  = r["quantity"]
    unit = fmt_money(r["unit_cost"], r["currency"])
    tot  = fmt_money(r["unit_cost"] * r["quantity"], r["currency"])
    return f"{date}: {item} ×{qty} @ {unit} = {tot}"

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
# ║                       ADD  FLOW                             ║
# ╚══════════════════════════════════════════════════════════════╝
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
    btns = [InlineKeyboardButton(p["name"], callback_data=f"si_part_{p.doc_id}") for p in partners]
    rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=InlineKeyboardMarkup(rows))
    return SI_PARTNER_SELECT

async def get_stockin_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["partner_id"] = pid
    stores = secure_db.all("stores")
    if not stores:
        await update.callback_query.edit_message_text(
            "No stores defined.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]])
        )
        return ConversationHandler.END
    btns = [InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"si_store_{s.doc_id}") for s in stores]
    rows = [btns[i:i+2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")])
    await update.callback_query.edit_message_text("Select store:", reply_markup=InlineKeyboardMarkup(rows))
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
    await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)(summary, reply_markup=kb)
    return SI_CONFIRM

@require_unlock
async def confirm_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "si_yes":
        await show_stockin_menu(update, context)
        return ConversationHandler.END

    d = context.user_data
    cur = _store_currency(d["store_id"])
    try:
        # === PATCH: Ledger first for unique related_id ===
        related_id = add_ledger_entry(
            account_type="partner",
            account_id=d["partner_id"],
            entry_type="stockin",
            related_id=None,
            amount=0,
            currency=cur,
            note=d.get("note", ""),
            date=d["date"],
            item_id=str(d["item_id"]),
            quantity=d["qty"],
            unit_price=d["cost"],
            store_id=d["store_id"]
        )
        # Now insert partner_inventory with this related_id
        partner_inv_id = secure_db.insert("partner_inventory", {
            "partner_id": d["partner_id"],
            "store_id":   d["store_id"],
            "item_id":    d["item_id"],
            "quantity":   d["qty"],
            "unit_cost":  d["cost"],
            "note":       d.get("note", ""),
            "date":       d["date"],
            "currency":   cur,
            "timestamp":  datetime.utcnow().isoformat(),
            "related_id": related_id  # always matches ledger
        })
        # store_inventory update unchanged...
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
    except Exception as e:
        try:
            if 'partner_inv_id' in locals():
                secure_db.remove("partner_inventory", [partner_inv_id])
        except Exception:
            pass
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
# ║                       VIEW  FLOW (FIXED RE-ENTRY)            ║
# ╚══════════════════════════════════════════════════════════════╝

@require_unlock
async def view_stockin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    # Clean up any old filter vars
    context.user_data.pop("view_partner_id", None)
    context.user_data.pop("view_time_filter", None)
    context.user_data.pop("view_page", None)
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]]))
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(p["name"], callback_data=f"si_view_part_{p.doc_id}") for p in partners]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="stockin_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return SI_VIEW_PARTNER

async def view_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data.update({"view_partner_id": pid, "view_page": 1, "view_time_filter": None})
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 M", callback_data="view_time_3m"),
         InlineKeyboardButton("📅 Last 6 M", callback_data="view_time_6m")],
        [InlineKeyboardButton("🗓️ All",      callback_data="view_time_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="view_stockin")],
    ])
    await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
    return SI_VIEW_TIME

async def view_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_time_filter"] = update.callback_query.data.split("_")[-1]
    context.user_data["view_page"] = 1
    return await send_view_page(update, context)

async def send_view_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid   = context.user_data.get("view_partner_id")
    period= context.user_data.get("view_time_filter")
    page  = context.user_data.get("view_page", 1)
    size  = 20

    if pid is None or period is None:
        # Something went wrong, reset to view start
        return await view_stockin_start(update, context)

    rows = [r for r in secure_db.all("partner_inventory") if r["partner_id"] == pid]
    rows = _filter_by_time(rows, period)
    rows = sorted(rows, key=lambda r: r.get("related_id", r.doc_id), reverse=True)
    total_pages = max(1, (len(rows)+size-1)//size)
    chunk = rows[(page-1)*size : page*size]
    if not chunk:
        await update.callback_query.edit_message_text(
            "No stock-ins in that window.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="view_stockin")]]))
        return ConversationHandler.END

    def _format_stockin_row(r):
        try:
            dt = datetime.fromisoformat(r["timestamp"])
        except Exception:
            dt = datetime.now()
        date = dt.strftime("%d/%m/%y")
        item = r["item_id"]
        qty  = r["quantity"]
        unit = fmt_money(r["unit_cost"], r["currency"])
        tot  = fmt_money(r["unit_cost"] * r["quantity"], r["currency"])
        return f"{date}: {item} ×{qty} @ {unit} = {tot}"

    lines = []
    for r in chunk:
        lines.append(f"{r.get('related_id', r.doc_id)}: {_format_stockin_row(r)}")
    text = (
        f"📄 **Stock-Ins**  P{page}/{total_pages}\n\n"
        + "\n".join(lines)
        + "\n\n(Reference number: leftmost)"
    )

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="view_prev"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="view_next"))
    nav.append(InlineKeyboardButton("🔙 Back", callback_data="view_stockin"))
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([nav]))
    return SI_VIEW_PAGE


async def handle_view_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "view_prev":
        context.user_data["view_page"] -= 1
    elif update.callback_query.data == "view_next":
        context.user_data["view_page"] += 1
    # Re-entry guard: always check the state vars
    return await send_view_page(update, context)



# ╔══════════════════════════════════════════════════════════════╗
# ║                       EDIT  FLOW                             ║
# ╚══════════════════════════════════════════════════════════════╝
@require_unlock
async def edit_stockin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="stockin_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"si_edit_part_{p.doc_id}")
               for p in partners]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="stockin_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return SI_EDIT_PARTNER

async def edit_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data.update({"edit_partner_id": pid, "edit_page": 1})
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 M", callback_data="edit_time_3m"),
         InlineKeyboardButton("📅 Last 6 M", callback_data="edit_time_6m")],
        [InlineKeyboardButton("🗓️ All",      callback_data="edit_time_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="edit_stockin")],
    ])
    await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
    return SI_EDIT_TIME

async def edit_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_time_filter"] = update.callback_query.data.split("_")[-1]
    context.user_data["edit_page"] = 1
    return await send_edit_page(update, context)

async def send_edit_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid   = context.user_data["edit_partner_id"]
    period= context.user_data["edit_time_filter"]
    page  = context.user_data["edit_page"]
    size  = 20

    rows = [r for r in secure_db.all("partner_inventory") if r["partner_id"] == pid]
    rows = _filter_by_time(rows, period)
    rows = sorted(rows, key=lambda r: r.get("related_id", r.doc_id), reverse=True)
    total_pages = max(1, (len(rows)+size-1)//size)
    chunk = rows[(page-1)*size : page*size]
    if not chunk:
        await update.callback_query.edit_message_text(
            "No records.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="edit_stockin")]]))
        return ConversationHandler.END

    def _format_stockin_row(r):
        try:
            dt = datetime.fromisoformat(r["timestamp"])
        except Exception:
            dt = datetime.now()
        date = dt.strftime("%d/%m/%y")
        item = r["item_id"]
        qty  = r["quantity"]
        unit = fmt_money(r["unit_cost"], r["currency"])
        tot  = fmt_money(r["unit_cost"] * r["quantity"], r["currency"])
        return f"{date}: {item} ×{qty} @ {unit} = {tot}"

    lines = []
    for r in chunk:
        lines.append(f"{r.get('related_id', r.doc_id)}: {_format_stockin_row(r)}")
    msg = (f"✏️ **Edit Stock-In**  P{page}/{total_pages}\n\n"
           + "\n".join(lines)
           + "\n\nReply with reference number (leftmost) or use ⬅️➡️")
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="edit_prev"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="edit_next"))
    nav.append(InlineKeyboardButton("🔙 Back", callback_data="edit_stockin"))
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([nav]))
    return SI_EDIT_PAGE




async def handle_edit_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "edit_prev":
        context.user_data["edit_page"] -= 1
    elif update.callback_query.data == "edit_next":
        context.user_data["edit_page"] += 1
    return await send_edit_page(update, context)

async def edit_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid = _extract_doc_id(update.message.text)
    if rid is None:
        await update.message.reply_text("Numeric reference number, please.")
        return SI_EDIT_PAGE
    q = Query()
    recs = secure_db.table("partner_inventory").search(q.related_id == rid)
    # Backward compatibility for legacy records:
    if not recs:
        recs = secure_db.table("partner_inventory").search(doc_id=rid)
    if not recs or recs[0]["partner_id"] != context.user_data["edit_partner_id"]:
        await update.message.reply_text("Reference not in this list.")
        return SI_EDIT_PAGE
    rec = recs[0]
    context.user_data.update({
        "edit_stock_related_id": rec.get("related_id", rec.doc_id),
        "orig_qty":      rec["quantity"],
        "store_id":      rec["store_id"],
    })
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Quantity",   callback_data="edit_field_qty")],
        [InlineKeyboardButton("Unit Cost",  callback_data="edit_field_cost")],
        [InlineKeyboardButton("Date",       callback_data="edit_field_date")],
        [InlineKeyboardButton("Note",       callback_data="edit_field_note")],
        [InlineKeyboardButton("🔙 Cancel",  callback_data="edit_stockin")],
    ])
    await update.message.reply_text(f"Editing record #{rec.get('related_id', rec.doc_id)}. Choose field:", reply_markup=kb)
    return SI_EDIT_FIELD



async def get_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    field = update.callback_query.data.split("_")[-1]
    context.user_data["edit_field"] = field
    if field == "qty":
        await update.callback_query.edit_message_text("New quantity:")
    elif field == "cost":
        await update.callback_query.edit_message_text("New unit cost:")
    elif field == "date":
        today = datetime.now().strftime("%d%m%Y")
        await update.callback_query.edit_message_text(
            f"New date DDMMYYYY (today {today}):")
    elif field == "note":
        await update.callback_query.edit_message_text("New note (or '-' to clear):")
    return SI_EDIT_NEWVAL

async def save_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_value"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="edit_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="edit_conf_no")]
    ])
    await update.message.reply_text(
        f"Change **{context.user_data['edit_field']}** "
        f"→ `{context.user_data['new_value']}` ?", reply_markup=kb)
    return SI_EDIT_CONFIRM

@require_unlock
async def confirm_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "edit_conf_yes":
        await show_stockin_menu(update, context)
        return ConversationHandler.END

    rid   = context.user_data["edit_stock_related_id"]
    field = context.user_data["edit_field"]
    val   = context.user_data["new_value"]

    q = Query()
    recs = secure_db.table("partner_inventory").search(q.related_id == rid)
    # Backward compatibility for legacy records:
    if not recs:
        recs = secure_db.table("partner_inventory").search(doc_id=rid)
    if not recs:
        await update.callback_query.edit_message_text("Record not found.")
        return ConversationHandler.END
    rec = recs[0]
    store_id = rec["store_id"]

    # Ledger edit tracking variables
    ledger_type = None
    ledger_args = {}

    try:
        doc_id = rec.doc_id
        if field == "qty":
            new_qty = int(val)
            delta   = new_qty - rec["quantity"]
            secure_db.update("partner_inventory", {"quantity": new_qty}, [doc_id])

            q2 = Query()
            inv = secure_db.table("store_inventory").get((q2.store_id == store_id) &
                                                        (q2.item_id == rec["item_id"]))
            if inv:
                secure_db.update("store_inventory",
                                {"quantity": inv["quantity"] + delta},
                                [inv.doc_id])
            ledger_type = "stockin_edit_qty"
            ledger_args = dict(
                account_type="partner",
                account_id=rec["partner_id"],
                store_id=rec["store_id"],
                item_id=rec["item_id"],
                quantity=new_qty,
                unit_price=rec["unit_cost"],
                amount=0,
                currency=rec["currency"],
                note=f"Edit qty (was {rec['quantity']})",
                date=rec["date"],
                related_id=rec.get("related_id", rec.doc_id)
            )
        elif field == "cost":
            old_cost = rec["unit_cost"]
            secure_db.update("partner_inventory", {"unit_cost": float(val)}, [doc_id])
            q2 = Query()
            inv = secure_db.table("store_inventory").get((q2.store_id == store_id) &
                                                        (q2.item_id == rec["item_id"]))
            if inv:
                secure_db.update("store_inventory", {"unit_cost": float(val)}, [inv.doc_id])
            ledger_type = "stockin_edit_cost"
            ledger_args = dict(
                account_type="partner",
                account_id=rec["partner_id"],
                store_id=rec["store_id"],
                item_id=rec["item_id"],
                quantity=rec["quantity"],
                unit_price=float(val),
                amount=0,
                currency=rec["currency"],
                note=f"Edit cost (was {old_cost})",
                date=rec["date"],
                related_id=rec.get("related_id", rec.doc_id)
            )
        elif field == "date":
            secure_db.update("partner_inventory", {"date": val}, [doc_id])
        elif field == "note":
            secure_db.update("partner_inventory", {"note": "" if val == "-" else val}, [doc_id])
        if ledger_type:
            add_ledger_entry(entry_type=ledger_type, **ledger_args)

    except Exception as e:
        # Rollback attempt
        if field == "qty":
            secure_db.update("partner_inventory", {"quantity": rec["quantity"]}, [doc_id])
            q2 = Query()
            inv = secure_db.table("store_inventory").get((q2.store_id == store_id) & (q2.item_id == rec["item_id"]))
            if inv:
                secure_db.update(
                    "store_inventory",
                    {"quantity": inv["quantity"] - (int(val) - rec["quantity"])},
                    [inv.doc_id]
                )
        elif field == "cost":
            secure_db.update("partner_inventory", {"unit_cost": rec["unit_cost"]}, [doc_id])
            q2 = Query()
            inv = secure_db.table("store_inventory").get((q2.store_id == store_id) & (q2.item_id == rec["item_id"]))
            if inv:
                secure_db.update(
                    "store_inventory",
                    {"unit_cost": rec["unit_cost"]},
                    [inv.doc_id]
                )
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
async def del_stockin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="stockin_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"si_del_part_{p.doc_id}")
               for p in partners]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="stockin_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return SI_DEL_PARTNER

async def del_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data.update({"del_partner_id": pid, "del_page": 1})
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 M", callback_data="del_time_3m"),
         InlineKeyboardButton("📅 Last 6 M", callback_data="del_time_6m")],
        [InlineKeyboardButton("🗓️ All",      callback_data="del_time_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="remove_stockin")],
    ])
    await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
    return SI_DEL_TIME

async def del_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_time_filter"] = update.callback_query.data.split("_")[-1]
    context.user_data["del_page"] = 1
    return await send_del_page(update, context)

async def send_del_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid   = context.user_data["del_partner_id"]
    period= context.user_data["del_time_filter"]
    page  = context.user_data["del_page"]
    size  = 20

    rows = [r for r in secure_db.all("partner_inventory") if r["partner_id"] == pid]
    rows = _filter_by_time(rows, period)
    rows = sorted(rows, key=lambda r: r.get("related_id", r.doc_id), reverse=True)
    total_pages = max(1, (len(rows)+size-1)//size)
    chunk = rows[(page-1)*size : page*size]
    if not chunk:
        await update.callback_query.edit_message_text(
            "No records.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="remove_stockin")]]))
        return ConversationHandler.END

    def _format_stockin_row(r):
        try:
            dt = datetime.fromisoformat(r["timestamp"])
        except Exception:
            dt = datetime.now()
        date = dt.strftime("%d/%m/%y")
        item = r["item_id"]
        qty  = r["quantity"]
        unit = fmt_money(r["unit_cost"], r["currency"])
        tot  = fmt_money(r["unit_cost"] * r["quantity"], r["currency"])
        return f"{date}: {item} ×{qty} @ {unit} = {tot}"

    lines = []
    for r in chunk:
        lines.append(f"{r.get('related_id', r.doc_id)}: {_format_stockin_row(r)}")
    msg = (f"🗑️ **Delete Stock-In**  P{page}/{total_pages}\n\n"
           + "\n".join(lines)
           + "\n\nReply with reference number (leftmost) or use ⬅️➡️")
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="del_prev"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="del_next"))
    nav.append(InlineKeyboardButton("🔙 Back", callback_data="remove_stockin"))
    await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([nav]))
    return SI_DEL_PAGE




async def handle_del_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "del_prev":
        context.user_data["del_page"] -= 1
    elif update.callback_query.data == "del_next":
        context.user_data["del_page"] += 1
    return await send_del_page(update, context)

async def del_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid = _extract_doc_id(update.message.text)
    if rid is None:
        await update.message.reply_text("Numeric ID, please.")
        return SI_DEL_PAGE
    q = Query()
    recs = secure_db.table("partner_inventory").search(q.related_id == rid)
    # Legacy fallback:
    if not recs:
        recs = secure_db.table("partner_inventory").search(doc_id=rid)
    if not recs or recs[0]["partner_id"] != context.user_data["del_partner_id"]:
        await update.message.reply_text("ID not in this list.")
        return SI_DEL_PAGE
    rec = recs[0]
    context.user_data["del_related_id"] = rec.get("related_id", rec.doc_id)
    context.user_data["del_doc_id"]     = rec.doc_id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="del_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="del_conf_no")]
    ])
    await update.message.reply_text(f"Delete record #{context.user_data['del_related_id']} ?", reply_markup=kb)
    return SI_DEL_CONFIRM

@require_unlock
async def del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "del_conf_yes":
        await show_stockin_menu(update, context)
        return ConversationHandler.END

    rid    = context.user_data["del_related_id"]
    doc_id = context.user_data["del_doc_id"]
    q = Query()
    recs = secure_db.table("partner_inventory").search(q.related_id == rid)
    if not recs:
        recs = secure_db.table("partner_inventory").search(doc_id=rid)
    if not recs:
        await update.callback_query.edit_message_text("Record not found.")
        return ConversationHandler.END
    rec = recs[0]

    try:
        add_ledger_entry(
            entry_type="stockin_delete",
            account_type="partner",
            account_id=rec["partner_id"],
            related_id=rec.get("related_id", rec.doc_id),
            amount=0,
            currency=rec["currency"],
            note=f"Stock-in deleted: {rec.get('note','')}",
            date=rec["date"],
            item_id=rec["item_id"],
            quantity=rec["quantity"],
            unit_price=rec["unit_cost"],
            store_id=rec["store_id"]
        )
    except Exception as e:
        await update.callback_query.edit_message_text(
            f"❌ Stock-In delete failed: {str(e)}"
        )
        return ConversationHandler.END

    try:
        if rec:
            q2 = Query()
            inv = secure_db.table("store_inventory").get((q2.store_id == rec["store_id"]) &
                                                        (q2.item_id  == rec["item_id"]))
            if inv:
                secure_db.update("store_inventory",
                                {"quantity": inv["quantity"] - rec["quantity"]},
                                [inv.doc_id])
        secure_db.remove("partner_inventory", [doc_id])
    except Exception as e:
        await update.callback_query.edit_message_text(
            f"❌ Stock-In delete failed: {str(e)}"
        )
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        f"✅ Stock-In #{rid} deleted.",
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
                         CallbackQueryHandler(show_stockin_menu,  pattern="^stockin_menu$"),
                         CallbackQueryHandler(view_stockin_start, pattern="^view_stockin$")],
        SI_VIEW_TIME:   [CallbackQueryHandler(view_set_filter,    pattern="^view_time_"),
                         CallbackQueryHandler(view_stockin_start, pattern="^view_stockin$")],
        SI_VIEW_PAGE:   [CallbackQueryHandler(handle_view_pagination, pattern="^view_(prev|next)$"),
                         CallbackQueryHandler(view_stockin_start,     pattern="^view_stockin$")],
    },
    fallbacks=[CommandHandler("cancel", show_stockin_menu)],
    per_message=False,
)

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
                         CallbackQueryHandler(show_stockin_menu,  pattern="^stockin_menu$"),
                         CallbackQueryHandler(view_stockin_start, pattern="^view_stockin$")],
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

