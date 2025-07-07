# handlers/stockin.py  – Stock-In module upgraded to “sales-style” flows
import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from tinydb import Query
from handlers.utils import require_unlock
from secure_db      import secure_db


# ───────────────────────────────────────────────────────────────
#  Conversation-state constants
# ───────────────────────────────────────────────────────────────
(
    SI_ADD_PARTNER,  SI_ADD_STORE,  SI_ADD_ITEM,  SI_ADD_QTY,  SI_ADD_COST,
    SI_ADD_NOTE,     SI_ADD_DATE,   SI_ADD_CONFIRM,

    SI_VIEW_PARTNER, SI_VIEW_TIME,  SI_VIEW_PAGE,

    SI_EDIT_PARTNER, SI_EDIT_TIME,  SI_EDIT_PAGE,
    SI_EDIT_QTY,     SI_EDIT_COST,  SI_EDIT_DATE, SI_EDIT_CONFIRM,

    SI_DEL_PARTNER,  SI_DEL_TIME,   SI_DEL_PAGE,  SI_DEL_CONFIRM,
) = range(23)

ROWS_PER_PAGE = 20   # same as sales.py


# ───────────────────────────────────────────────────────────────
#  Helper – adjust store inventory on add / edit / delete
# ───────────────────────────────────────────────────────────────
def _bump_store_inventory(store_id: int, item_id, delta: int) -> None:
    tbl = secure_db.table("store_inventory")
    q   = (Query().store_id == store_id) & (Query().item_id == item_id)
    row = tbl.get(q)
    if row:
        secure_db.update("store_inventory",
                         {"quantity": max(row["quantity"] + delta, 0)},
                         [row.doc_id])
    elif delta > 0:
        secure_db.insert("store_inventory",
                         {"store_id": store_id, "item_id": item_id, "quantity": delta})


def _months_filter(rows, months: int):
    if months <= 0:
        return rows
    cutoff = datetime.utcnow().replace(day=1)
    m = cutoff.month - months
    y = cutoff.year
    if m <= 0:
        m += 12
        y -= 1
    cutoff = cutoff.replace(year=y, month=m)
    return [r for r in rows if datetime.strptime(r["date"], "%d%m%Y") >= cutoff]


# ───────────────────────────────────────────────────────────────
#  Sub-menu (called from main menu & after flows)
# ───────────────────────────────────────────────────────────────
async def show_stockin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await (update.callback_query.answer() if update.callback_query else update.message.reply_text(""))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Stock-In",    callback_data="add_stockin")],
        [InlineKeyboardButton("👀 View Stock-Ins",  callback_data="view_stockin")],
        [InlineKeyboardButton("✏️ Edit Stock-In",   callback_data="edit_stockin")],
        [InlineKeyboardButton("🗑️ Remove Stock-In", callback_data="remove_stockin")],
        [InlineKeyboardButton("🔙 Back",            callback_data="main_menu")],
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text("📥 Stock-In: choose an action", reply_markup=kb)
    else:
        await update.message.reply_text("📥 Stock-In: choose an action", reply_markup=kb)


# ======================================================================
#                              ADD  FLOW  (unchanged UX)
# ======================================================================
@require_unlock
async def add_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "⚠️ No partners available.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"si_add_part_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return SI_ADD_PARTNER


async def get_add_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["partner_id"] = int(update.callback_query.data.split("_")[-1])

    stores = secure_db.all("stores")
    if not stores:
        await update.callback_query.edit_message_text(
            "⚠️ No stores configured.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(s["name"], callback_data=f"si_add_store_{s.doc_id}") for s in stores]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Allocate to which store?", reply_markup=kb)
    return SI_ADD_STORE


async def get_add_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["store_id"] = int(update.callback_query.data.split("_")[-1])
    await update.callback_query.edit_message_text("Enter item ID or name:")
    return SI_ADD_ITEM


async def get_add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item = update.message.text.strip()
    Item = Query()
    if not secure_db.table("items").get((Item.item_id == item) | (Item.name == item)):
        secure_db.insert("items", {"item_id": item, "name": item})
    context.user_data["item_id"] = item
    await update.message.reply_text("Enter quantity (integer):")
    return SI_ADD_QTY


async def get_add_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        q = int(update.message.text); assert q > 0
    except:
        await update.message.reply_text("❌ Positive integer please."); return SI_ADD_QTY
    context.user_data["qty"] = q
    await update.message.reply_text("Enter cost per unit (e.g. 12.50):")
    return SI_ADD_COST


async def get_add_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: cost = float(update.message.text)
    except: await update.message.reply_text("❌ Number please."); return SI_ADD_COST
    context.user_data["cost"] = cost
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="si_add_note_skip")]])
    await update.message.reply_text("Enter optional note or Skip:", reply_markup=kb)
    return SI_ADD_NOTE


async def get_add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = "" if (update.callback_query and update.callback_query.data.endswith("skip")) else update.message.text.strip()
    if update.callback_query:
        await update.callback_query.answer()
    context.user_data["note"] = note
    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="si_add_date_skip")]])
    prompt = f"Enter stock-in date DDMMYYYY or Skip ({today}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return SI_ADD_DATE


async def get_add_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date = datetime.now().strftime("%d%m%Y")
    else:
        date = update.message.text.strip()
        try: datetime.strptime(date, "%d%m%Y")
        except ValueError:
            await update.message.reply_text("❌ Format DDMMYYYY."); return SI_ADD_DATE
    context.user_data["date"] = date
    return await confirm_add_prompt(update, context)


async def confirm_add_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    summ = (f"Partner ID: {d['partner_id']}\nStore ID: {d['store_id']}\nItem: {d['item_id']}\n"
            f"Qty: {d['qty']}\nCost: {d['cost']:.2f}\nNote: {d.get('note') or '—'}\nDate: {d['date']}")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data="si_add_conf_yes"),
                                InlineKeyboardButton("❌ Cancel",  callback_data="si_add_conf_no")]])
    if update.callback_query:
        await update.callback_query.edit_message_text(summ, reply_markup=kb)
    else:
        await update.message.reply_text(summ, reply_markup=kb)
    return SI_ADD_CONFIRM


@require_unlock
async def confirm_add_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("no"):
        await show_stockin_menu(update, context); return ConversationHandler.END
    d = context.user_data
    rec_id = secure_db.insert("partner_inventory", {
        "partner_id": d["partner_id"], "store_id": d["store_id"], "item_id": d["item_id"],
        "quantity": d["qty"], "cost": d["cost"], "note": d.get("note", ""),
        "date": d["date"], "timestamp": datetime.utcnow().isoformat()
    })
    _bump_store_inventory(d["store_id"], d["item_id"], d["qty"])
    await update.callback_query.edit_message_text(
        f"✅ Stock-In recorded (ID {rec_id}).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]]))
    return ConversationHandler.END
# ======================================================================
#                          VIEW  FLOW  (Partner → Period → Pages)
# ======================================================================
@require_unlock
async def view_stockin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"si_view_part_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return SI_VIEW_PARTNER


async def view_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_pid"] = int(update.callback_query.data.split("_")[-1])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M", callback_data="si_view_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M", callback_data="si_view_filt_6m")],
        [InlineKeyboardButton("🗓️ All",     callback_data="si_view_filt_all")],
        [InlineKeyboardButton("🔙 Back",    callback_data="view_stockin")]
    ])
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return SI_VIEW_TIME


async def view_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_period"] = update.callback_query.data.split("_")[-1]   # 3m / 6m / all
    context.user_data["view_page"]   = 1
    return await render_view_page(update, context)


async def render_view_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid   = context.user_data["view_pid"]
    period= context.user_data["view_period"]
    page  = context.user_data["view_page"]

    rows = [r for r in secure_db.all("partner_inventory") if r["partner_id"] == pid]
    if period != "all":
        rows = _months_filter(rows, int(period.rstrip("m")))
    rows.sort(key=lambda r: datetime.strptime(r["date"], "%d%m%Y"), reverse=True)

    total = len(rows)
    start, end = (page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No stock-ins for that period."
    else:
        lines=[]
        for r in chunk:
            itm = secure_db.table("items").get(Query().item_id == r["item_id"]) or {}
            lines.append(f"[{r.doc_id}] Item {itm.get('name', r['item_id'])} "
                         f"x{r['quantity']} @ {r['cost']} on {r['date']}")
        text = f"📥 Stock-Ins P{page} / {(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n" + "\n".join(lines)

    nav=[]
    if start>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="si_view_prev"))
    if end<total: nav.append(InlineKeyboardButton("➡️ Next",callback_data="si_view_next"))
    kb=InlineKeyboardMarkup([nav,[InlineKeyboardButton("🔙 Back",callback_data="view_stockin")]])

    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return SI_VIEW_PAGE


async def view_paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("prev"):
        context.user_data["view_page"] -= 1
    else:
        context.user_data["view_page"] += 1
    return await render_view_page(update, context)


# ======================================================================
#                          EDIT  FLOW  (Partner → Period → Pages)
# ======================================================================
@require_unlock
async def edit_stockin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]]))
        return ConversationHandler.END
    buttons=[InlineKeyboardButton(p["name"],callback_data=f"si_edit_part_{p.doc_id}") for p in partners]
    kb=InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select partner:",reply_markup=kb)
    return SI_EDIT_PARTNER


async def edit_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_pid"]=int(update.callback_query.data.split("_")[-1])
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M",callback_data="si_edit_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M",callback_data="si_edit_filt_6m")],
        [InlineKeyboardButton("🗓️ All",    callback_data="si_edit_filt_all")],
        [InlineKeyboardButton("🔙 Back",   callback_data="edit_stockin")]])
    await update.callback_query.edit_message_text("Choose period:",reply_markup=kb)
    return SI_EDIT_TIME


async def edit_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_period"]=update.callback_query.data.split("_")[-1]
    context.user_data["edit_page"]=1
    return await render_edit_page(update,context)


async def render_edit_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid=context.user_data["edit_pid"]; period=context.user_data["edit_period"]; page=context.user_data["edit_page"]
    rows=[r for r in secure_db.all("partner_inventory") if r["partner_id"]==pid]
    if period!="all": rows=_months_filter(rows,int(period.rstrip("m")))
    rows.sort(key=lambda r:datetime.strptime(r["date"],"%d%m%Y"),reverse=True)
    total=len(rows); start,end=(page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk=rows[start:end]
    if not chunk: text="No stock-ins."
    else:
        lines=[f"[{r.doc_id}] Item {r['item_id']} x{r['quantity']} @ {r['cost']}" for r in chunk]
        text=f"✏️ Edit Stock-Ins P{page}/{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"+"\n".join(lines)
        text+="\n\nSend DocID to edit:"
    nav=[]
    if start>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="si_edit_prev"))
    if end<total: nav.append(InlineKeyboardButton("➡️ Next",callback_data="si_edit_next"))
    kb=InlineKeyboardMarkup([nav,[InlineKeyboardButton("🔙 Back",callback_data="edit_stockin")]])
    await update.callback_query.edit_message_text(text,reply_markup=kb)
    return SI_EDIT_PAGE


async def edit_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_page"] += (-1 if update.callback_query.data.endswith("prev") else 1)
    return await render_edit_page(update,context)


async def edit_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sid=int(update.message.text.strip())
        rec=secure_db.table("partner_inventory").get(doc_id=sid); assert rec
        if rec["partner_id"]!=context.user_data["edit_pid"]:
            raise ValueError
    except Exception:
        await update.message.reply_text("❌ Invalid ID; try again:"); return SI_EDIT_PAGE
    context.user_data["edit_rec"]=rec
    await update.message.reply_text("New quantity:"); return SI_EDIT_QTY


async def edit_new_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: q=int(update.message.text); assert q>0
    except: await update.message.reply_text("Positive integer please."); return SI_EDIT_QTY
    context.user_data["new_qty"]=q
    await update.message.reply_text("New cost per unit:"); return SI_EDIT_COST


async def edit_new_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: c=float(update.message.text)
    except: await update.message.reply_text("Number please."); return SI_EDIT_COST
    context.user_data["new_cost"]=c
    today=datetime.now().strftime("%d%m%Y")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip",callback_data="si_edit_date_skip")]])
    await update.message.reply_text(f"New date DDMMYYYY or Skip ({today}):",reply_markup=kb)
    return SI_EDIT_DATE


async def edit_new_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date=datetime.now().strftime("%d%m%Y")
    else:
        date=update.message.text.strip()
        try: datetime.strptime(date,"%d%m%Y")
        except ValueError:
            await update.message.reply_text("Format DDMMYYYY."); return SI_EDIT_DATE
    context.user_data["new_date"]=date
    d=context.user_data
    summary=(f"Qty: {d['new_qty']}\nCost: {d['new_cost']}\nDate: {date}\n\nSave?")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Save",callback_data="si_edit_conf_yes"),
                              InlineKeyboardButton("❌ Cancel",callback_data="si_edit_conf_no")]])
    await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)(
        summary,reply_markup=kb)
    return SI_EDIT_CONFIRM


@require_unlock
async def edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("_no"):
        await show_stockin_menu(update,context); return ConversationHandler.END
    rec=context.user_data["edit_rec"]; delta=context.user_data["new_qty"]-rec["quantity"]
    secure_db.update("partner_inventory",{
        "quantity":context.user_data["new_qty"],
        "cost":context.user_data["new_cost"],
        "date":context.user_data["new_date"]},[rec.doc_id])
    _bump_store_inventory(rec["store_id"],rec["item_id"],delta)
    await update.callback_query.edit_message_text(
        "✅ Stock-In updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]]))
    return ConversationHandler.END


# ======================================================================
#                          DELETE  FLOW  (Partner → Period → Pages)
# ======================================================================
@require_unlock
async def del_stockin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners=secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]]))
        return ConversationHandler.END
    buttons=[InlineKeyboardButton(p["name"],callback_data=f"si_del_part_{p.doc_id}") for p in partners]
    kb=InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select partner:",reply_markup=kb)
    return SI_DEL_PARTNER


async def del_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_pid"]=int(update.callback_query.data.split("_")[-1])
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M",callback_data="si_del_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M",callback_data="si_del_filt_6m")],
        [InlineKeyboardButton("🗓️ All",    callback_data="si_del_filt_all")],
        [InlineKeyboardButton("🔙 Back",   callback_data="remove_stockin")]])
    await update.callback_query.edit_message_text("Choose period:",reply_markup=kb)
    return SI_DEL_TIME


async def del_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_period"]=update.callback_query.data.split("_")[-1]
    context.user_data["del_page"]=1
    return await render_del_page(update,context)


async def render_del_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid=context.user_data["del_pid"]; period=context.user_data["del_period"]; page=context.user_data["del_page"]
    rows=[r for r in secure_db.all("partner_inventory") if r["partner_id"]==pid]
    if period!="all": rows=_months_filter(rows,int(period.rstrip("m")))
    rows.sort(key=lambda r:datetime.strptime(r["date"],"%d%m%Y"),reverse=True)
    total=len(rows); start,end=(page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk=rows[start:end]
    if not chunk: text="No stock-ins."
    else:
        lines=[f"[{r.doc_id}] Item {r['item_id']} x{r['quantity']} @ {r['cost']}" for r in chunk]
        text=f"🗑️ Delete Stock-Ins P{page}/{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"+"\n".join(lines)
        text+="\n\nSend DocID to delete:"
    nav=[]
    if start>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="si_del_prev"))
    if end<total: nav.append(InlineKeyboardButton("➡️ Next",callback_data="si_del_next"))
    kb=InlineKeyboardMarkup([nav,[InlineKeyboardButton("🔙 Back",callback_data="remove_stockin")]])
    await update.callback_query.edit_message_text(text,reply_markup=kb)
    return SI_DEL_PAGE


async def del_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_page"] += (-1 if update.callback_query.data.endswith("prev") else 1)
    return await render_del_page(update,context)


async def del_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sid=int(update.message.text.strip())
        rec=secure_db.table("partner_inventory").get(doc_id=sid); assert rec
        if rec["partner_id"]!=context.user_data["del_pid"]:
            raise ValueError
    except Exception:
        await update.message.reply_text("❌ Invalid ID; try again:"); return SI_DEL_PAGE
    context.user_data["del_rec"]=rec
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes",callback_data="si_del_conf_yes"),
                              InlineKeyboardButton("❌ No", callback_data="si_del_conf_no")]])
    await update.message.reply_text(f"Delete Stock-In [{sid}]?",reply_markup=kb)
    return SI_DEL_CONFIRM


@require_unlock
async def del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("_no"):
        await show_stockin_menu(update,context); return ConversationHandler.END
    rec=context.user_data["del_rec"]
    secure_db.remove("partner_inventory",[rec.doc_id])
    _bump_store_inventory(rec["store_id"],rec["item_id"],-rec["quantity"])
    await update.callback_query.edit_message_text(
        "✅ Stock-In deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]]))
    return ConversationHandler.END


# ======================================================================
#                   REGISTER  ALL  HANDLERS  FOR  MODULE
# ======================================================================
def register_stockin_handlers(app: Application):
    # Sub-menu
    app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))

    # ----------------- Add conversation -----------------
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add_stockin", add_stockin),
                      CallbackQueryHandler(add_stockin, pattern="^add_stockin$")],
        states={
            SI_ADD_PARTNER:[CallbackQueryHandler(get_add_partner, pattern="^si_add_part_\\d+$")],
            SI_ADD_STORE:  [CallbackQueryHandler(get_add_store,  pattern="^si_add_store_\\d+$")],
            SI_ADD_ITEM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_item)],
            SI_ADD_QTY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_qty)],
            SI_ADD_COST:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_cost)],
            SI_ADD_NOTE:   [CallbackQueryHandler(get_add_note,  pattern="^si_add_note_skip$"),
                            MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_note)],
            SI_ADD_DATE:   [CallbackQueryHandler(get_add_date,  pattern="^si_add_date_skip$"),
                            MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_date)],
            SI_ADD_CONFIRM:[CallbackQueryHandler(confirm_add_stockin, pattern="^si_add_conf_")],
        },
        fallbacks=[CommandHandler("cancel", show_stockin_menu)],
        per_message=False))

    # ----------------- View conversation -----------------
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(view_stockin_start, pattern="^view_stockin$")],
        states={
            SI_VIEW_PARTNER:[CallbackQueryHandler(view_choose_period, pattern="^si_view_part_\\d+$")],
            SI_VIEW_TIME:   [CallbackQueryHandler(view_set_filter,    pattern="^si_view_filt_")],
            SI_VIEW_PAGE:   [CallbackQueryHandler(view_paginate,      pattern="^si_view_(prev|next)$")],
        },
        fallbacks=[CommandHandler("cancel", show_stockin_menu)],
        per_message=False))

    # ----------------- Edit conversation -----------------
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_stockin_start, pattern="^edit_stockin$")],
        states={
            SI_EDIT_PARTNER:[CallbackQueryHandler(edit_choose_period, pattern="^si_edit_part_\\d+$")],
            SI_EDIT_TIME:   [CallbackQueryHandler(edit_set_filter,    pattern="^si_edit_filt_")],
            SI_EDIT_PAGE:   [CallbackQueryHandler(edit_page_nav,      pattern="^si_edit_(prev|next)$"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, edit_pick_doc)],
            SI_EDIT_QTY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_qty)],
            SI_EDIT_COST:   [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_cost)],
            SI_EDIT_DATE:   [CallbackQueryHandler(edit_new_date, pattern="^si_edit_date_skip$"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_date)],
            SI_EDIT_CONFIRM:[CallbackQueryHandler(edit_save,     pattern="^si_edit_conf_")],
        },
        fallbacks=[CommandHandler("cancel", show_stockin_menu)],
        per_message=False))

    # ----------------- Delete conversation -----------------
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(del_stockin_start, pattern="^remove_stockin$")],
        states={
            SI_DEL_PARTNER:[CallbackQueryHandler(del_choose_period, pattern="^si_del_part_\\d+$")],
            SI_DEL_TIME:   [CallbackQueryHandler(del_set_filter,   pattern="^si_del_filt_")],
            SI_DEL_PAGE:   [CallbackQueryHandler(del_page_nav,     pattern="^si_del_(prev|next)$"),
                            MessageHandler(filters.TEXT & ~filters.COMMAND, del_pick_doc)],
            SI_DEL_CONFIRM:[CallbackQueryHandler(del_confirm,      pattern="^si_del_conf_")],
        },
        fallbacks=[CommandHandler("cancel", show_stockin_menu)],
        per_message=False))
