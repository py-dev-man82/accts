# handlers/stockin.py  •  Compatible with the advanced sales-style flows
import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ConversationHandler,
    ContextTypes, MessageHandler, filters
)
from tinydb import Query
from handlers.utils import require_unlock
from secure_db      import secure_db

# ───────────────────────────────────────────────────────────────
#  Conversation-state constants
# ───────────────────────────────────────────────────────────────
(
    SI_PARTNER_SELECT, SI_STORE_SELECT, SI_ITEM_SELECT, SI_QTY, SI_COST,
    SI_NOTE, SI_DATE, SI_CONFIRM,
    SI_EDIT_SELECT,   SI_EDIT_QTY, SI_EDIT_COST, SI_EDIT_DATE, SI_EDIT_CONFIRM,
    SI_DELETE_SELECT, SI_DELETE_CONFIRM,
) = range(15)

STOCKIN_PER_PAGE = 20  # rows per page in view / edit / delete

# ───────────────────────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────────────────────
def adjust_store_inventory(store_id: int, item_id, delta: int) -> None:
    """Add *delta* to a store’s inventory (negative to subtract)."""
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

def _filter_by_months(rows, months: int):
    """Return only rows dated within the last *months* calendar months."""
    if months <= 0:
        return rows
    cutoff = datetime.utcnow().replace(day=1)
    # naïve month subtraction good enough for <= 12
    m = cutoff.month - months
    y = cutoff.year
    if m <= 0:
        m += 12
        y -= 1
    cutoff = cutoff.replace(year=y, month=m)
    return [r for r in rows if datetime.strptime(r["date"], "%d%m%Y") >= cutoff]

# ───────────────────────────────────────────────────────────────
#  Sub-menu
# ───────────────────────────────────────────────────────────────
async def edit_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M", callback_data="edit_si_filter_3m")],
        [InlineKeyboardButton("📆 Last 6 M", callback_data="edit_si_filter_6m")],
        [InlineKeyboardButton("📆 Show All", callback_data="edit_si_filter_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="stockin_menu")]
    ])
    await update.callback_query.edit_message_text(
        "✏️ Edit Stock-In: choose period", reply_markup=kb
    )
    # ▶️ **ADD THIS RETURN**
    return SI_EDIT_SELECT


# ======================================================================
#                              ADD  FLOW
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
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"si_part_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a partner:", reply_markup=kb)
    return SI_PARTNER_SELECT

async def get_stockin_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["partner_id"] = int(update.callback_query.data.split("_")[-1])

    stores = secure_db.all("stores")
    if not stores:
        await update.callback_query.edit_message_text(
            "⚠️ No stores configured.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="stockin_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(s["name"], callback_data=f"si_store_{s.doc_id}") for s in stores]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Allocate to which store?", reply_markup=kb)
    return SI_STORE_SELECT

async def get_stockin_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["store_id"] = int(update.callback_query.data.split("_")[-1])
    await update.callback_query.edit_message_text("Enter item ID or name:")
    return SI_ITEM_SELECT

async def get_stockin_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item = update.message.text.strip()
    Item = Query()
    if not secure_db.table("items").get((Item.item_id==item)|(Item.name==item)):
        secure_db.insert("items", {"item_id": item, "name": item})
    context.user_data["item_id"] = item
    await update.message.reply_text("Enter quantity (integer):")
    return SI_QTY

async def get_stockin_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text); assert qty>0
    except:
        await update.message.reply_text("❌ Positive integer please."); return SI_QTY
    context.user_data["qty"] = qty
    await update.message.reply_text("Enter cost per unit (e.g. 12.50):"); return SI_COST

async def get_stockin_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: cost=float(update.message.text)
    except: await update.message.reply_text("❌ Number please."); return SI_COST
    context.user_data["cost"] = cost
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note",callback_data="si_note_skip")]])
    await update.message.reply_text("Enter optional note or Skip:",reply_markup=kb)
    return SI_NOTE

async def get_stockin_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer(); note=""
    else: note=update.message.text.strip()
    context.user_data["note"]=note
    today=datetime.now().strftime("%d%m%Y")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date",callback_data="si_date_skip")]])
    prompt=f"Enter stock-in date DDMMYYYY or Skip for today ({today}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt,reply_markup=kb)
    else:
        await update.message.reply_text(prompt,reply_markup=kb)
    return SI_DATE

async def get_stockin_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer(); date=datetime.now().strftime("%d%m%Y")
    else:
        date=update.message.text.strip()
        try: datetime.strptime(date,"%d%m%Y")
        except ValueError:
            await update.message.reply_text("❌ Format DDMMYYYY."); return SI_DATE
    context.user_data["date"]=date
    return await confirm_stockin_prompt(update,context)

async def confirm_stockin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d=context.user_data
    summary=(f"Partner ID: {d['partner_id']}\nStore ID: {d['store_id']}\nItem: {d['item_id']}\n"
             f"Qty: {d['qty']}\nCost: {d['cost']:.2f}\nNote: {d.get('note') or '—'}\nDate: {d['date']}")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm",callback_data="si_conf_yes"),
                              InlineKeyboardButton("❌ Cancel", callback_data="si_conf_no")]])
    if update.callback_query: await update.callback_query.edit_message_text(summary,reply_markup=kb)
    else: await update.message.reply_text(summary,reply_markup=kb)
    return SI_CONFIRM

@require_unlock
async def confirm_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data!="si_conf_yes":
        await show_stockin_menu(update,context); return ConversationHandler.END
    d=context.user_data
    rec_id=secure_db.insert("partner_inventory",{
        "partner_id":d["partner_id"],"store_id":d["store_id"],"item_id":d["item_id"],
        "quantity":d["qty"],"cost":d["cost"],"note":d.get("note",""),"date":d["date"],
        "timestamp":datetime.utcnow().isoformat()})
    adjust_store_inventory(d["store_id"],d["item_id"],d["qty"])
    await update.callback_query.edit_message_text(
        f"✅ Stock-In recorded (ID {rec_id}).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]]))
    return ConversationHandler.END

# ======================================================================
#                          VIEW  FLOW  (paged)
# ======================================================================
async def view_stockins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M",callback_data="stockin_filter_3m")],
        [InlineKeyboardButton("📆 Last 6 M",callback_data="stockin_filter_6m")],
        [InlineKeyboardButton("📆 Show All", callback_data="stockin_filter_all")],
        [InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]
    ])
    await update.callback_query.edit_message_text("📥 View Stock-Ins: choose period",reply_markup=kb)

async def view_stockins_filtered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    filt=update.callback_query.data.split("_")[-1]
    context.user_data["v"]={"filter":filt,"page":1}
    await _render_stockin_page(update,context)

async def _render_stockin_page(update,context):
    cfg=context.user_data["v"]; filt=cfg["filter"]; page=cfg["page"]
    rows=secure_db.all("partner_inventory")
    if filt!="all": rows=_filter_by_months(rows,int(filt.rstrip("m")))
    rows.sort(key=lambda r:datetime.strptime(r["date"],"%d%m%Y"),reverse=True)
    total=len(rows); start=(page-1)*STOCKIN_PER_PAGE; end=start+STOCKIN_PER_PAGE
    chunk=rows[start:end]
    if not chunk: text="No stock-ins in that period."
    else:
        lines=[]
        for r in chunk:
            p=secure_db.table("partners").get(doc_id=r["partner_id"]) or {}
            itm=secure_db.table("items").get(Query().item_id==r["item_id"]) or {}
            lines.append(f"[{r.doc_id}] {p.get('name','?')}: {itm.get('name',r['item_id'])} "
                         f"x{r['quantity']} @ {r['cost']:.2f} on {r['date']} | {r.get('note','')}")
        text=f"📥 Stock-Ins  Page {page}\n\n"+"\n".join(lines)
    nav=[]
    if start>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="stockin_prev"))
    if end<total: nav.append(InlineKeyboardButton("➡️ Next",callback_data="stockin_next"))
    kb=InlineKeyboardMarkup([nav,[InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]])
    await update.callback_query.edit_message_text(text,reply_markup=kb)

async def view_stockins_prev(u,c): c.user_data["v"]["page"]-=1; await _render_stockin_page(u,c)
async def view_stockins_next(u,c): c.user_data["v"]["page"]+=1; await _render_stockin_page(u,c)

# ======================================================================
#                          EDIT  FLOW  (paged)
# ======================================================================
async def edit_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M",callback_data="edit_si_filter_3m")],
        [InlineKeyboardButton("📆 Last 6 M",callback_data="edit_si_filter_6m")],
        [InlineKeyboardButton("📆 Show All", callback_data="edit_si_filter_all")],
        [InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]
    ])
    await update.callback_query.edit_message_text("✏️ Edit Stock-In: choose period",reply_markup=kb)

async def edit_si_filtered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    filt=update.callback_query.data.split("_")[-1]
    context.user_data["e"]={"filter":filt,"page":1}
    await _render_edit_page(update,context)

async def _render_edit_page(update,context):
    cfg=context.user_data["e"]; filt=cfg["filter"]; page=cfg["page"]
    rows=secure_db.all("partner_inventory")
    if filt!="all": rows=_filter_by_months(rows,int(filt.rstrip("m")))
    rows.sort(key=lambda r:datetime.strptime(r["date"],"%d%m%Y"),reverse=True)
    total=len(rows); start=(page-1)*STOCKIN_PER_PAGE; end=start+STOCKIN_PER_PAGE
    chunk=rows[start:end]
    if not chunk: text="No stock-ins."
    else:
        lines=[f"[{r.doc_id}] Partner {r['partner_id']} Item {r['item_id']} x{r['quantity']} @ {r['cost']}"
               for r in chunk]
        text=f"✏️ Edit Stock-Ins  Page {page}\n\n"+"\n".join(lines)
        text+="\n\nSend the DocID to edit:"
    nav=[]
    if start>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="edit_si_prev"))
    if end<total: nav.append(InlineKeyboardButton("➡️ Next",callback_data="edit_si_next"))
    kb=InlineKeyboardMarkup([nav,[InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]])
    await update.callback_query.edit_message_text(text,reply_markup=kb)
    return SI_EDIT_SELECT

async def edit_si_prev(u,c): c.user_data["e"]["page"]-=1; await _render_edit_page(u,c)
async def edit_si_next(u,c): c.user_data["e"]["page"]+=1; await _render_edit_page(u,c)

async def get_edit_stockin_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        doc=int(update.message.text.strip())
        rec=secure_db.table("partner_inventory").get(doc_id=doc); assert rec
    except Exception:
        await update.message.reply_text("❌ Invalid ID, try again:"); return SI_EDIT_SELECT
    context.user_data["edit"]={"id":doc,"rec":rec}
    await update.message.reply_text("Enter new quantity:"); return SI_EDIT_QTY

async def get_edit_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: qty=int(update.message.text); assert qty>0
    except: await update.message.reply_text("Positive integer please."); return SI_EDIT_QTY
    context.user_data["edit"]["new_qty"]=qty
    await update.message.reply_text("Enter new cost per unit:"); return SI_EDIT_COST

async def get_edit_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: cost=float(update.message.text)
    except: await update.message.reply_text("Number please."); return SI_EDIT_COST
    context.user_data["edit"]["new_cost"]=cost
    today=datetime.now().strftime("%d%m%Y")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip",callback_data="edate_skip")]])
    await update.message.reply_text(f"Enter new date DDMMYYYY or Skip ({today}):",reply_markup=kb)
    return SI_EDIT_DATE

async def get_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer(); date=datetime.now().strftime("%d%m%Y")
    else:
        date=update.message.text.strip()
        try: datetime.strptime(date,"%d%m%Y")
        except ValueError:
            await update.message.reply_text("Format DDMMYYYY."); return SI_EDIT_DATE
    ed=context.user_data["edit"]; ed["new_date"]=date
    summary=(f"Qty: {ed['new_qty']}\nCost: {ed['new_cost']:.2f}\nDate: {date}\n\nSave?")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Save",callback_data="edit_conf_yes"),
                              InlineKeyboardButton("❌ Cancel",callback_data="edit_conf_no")]])
    if update.callback_query: await update.callback_query.edit_message_text(summary,reply_markup=kb)
    else: await update.message.reply_text(summary,reply_markup=kb)
    return SI_EDIT_CONFIRM

@require_unlock
async def confirm_edit_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data!="edit_conf_yes":
        await show_stockin_menu(update,context); return ConversationHandler.END
    ed=context.user_data["edit"]; rec=ed["rec"]
    delta=ed["new_qty"]-rec["quantity"]
    secure_db.update("partner_inventory",{
        "quantity":ed["new_qty"],"cost":ed["new_cost"],"date":ed["new_date"]},[ed["id"]])
    adjust_store_inventory(rec["store_id"],rec["item_id"],delta)
    await update.callback_query.edit_message_text(
        "✅ Stock-In updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]]))
    return ConversationHandler.END

# ======================================================================
#                          DELETE  FLOW  (paged)
# ======================================================================
async def remove_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M", callback_data="del_si_filter_3m")],
        [InlineKeyboardButton("📆 Last 6 M", callback_data="del_si_filter_6m")],
        [InlineKeyboardButton("📆 Show All", callback_data="del_si_filter_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="stockin_menu")]
    ])
    await update.callback_query.edit_message_text(
        "🗑️ Delete Stock-In: choose period", reply_markup=kb
    )
    # ▶️ **ADD THIS RETURN**
    return SI_DELETE_SELECT


async def del_si_filtered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    filt=update.callback_query.data.split("_")[-1]
    context.user_data["d"]={"filter":filt,"page":1}
    await _render_delete_page(update,context)

async def _render_delete_page(update,context):
    cfg=context.user_data["d"]; filt=cfg["filter"]; page=cfg["page"]
    rows=secure_db.all("partner_inventory")
    if filt!="all": rows=_filter_by_months(rows,int(filt.rstrip("m")))
    rows.sort(key=lambda r:datetime.strptime(r["date"],"%d%m%Y"),reverse=True)
    total=len(rows); start=(page-1)*STOCKIN_PER_PAGE; end=start+STOCKIN_PER_PAGE
    chunk=rows[start:end]
    if not chunk: text="No stock-ins."
    else:
        lines=[f"[{r.doc_id}] Partner {r['partner_id']} Item {r['item_id']} x{r['quantity']} @ {r['cost']}"
               for r in chunk]
        text=f"🗑️ Delete Stock-Ins  Page {page}\n\n"+"\n".join(lines)
        text+="\n\nSend the DocID to delete:"
    nav=[]
    if start>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="del_si_prev"))
    if end<total: nav.append(InlineKeyboardButton("➡️ Next",callback_data="del_si_next"))
    kb=InlineKeyboardMarkup([nav,[InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]])
    await update.callback_query.edit_message_text(text,reply_markup=kb)
    return SI_DELETE_SELECT

async def del_si_prev(u,c): c.user_data["d"]["page"]-=1; await _render_delete_page(u,c)
async def del_si_next(u,c): c.user_data["d"]["page"]+=1; await _render_delete_page(u,c)

async def get_delete_stockin_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        did=int(update.message.text.strip())
        rec=secure_db.table("partner_inventory").get(doc_id=did); assert rec
    except Exception:
        await update.message.reply_text("❌ Invalid ID, try again:"); return SI_DELETE_SELECT
    context.user_data["del"]={"id":did,"rec":rec}
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes",callback_data="del_conf_yes"),
                              InlineKeyboardButton("❌ No", callback_data="del_conf_no")]])
    await update.message.reply_text(
        f"Delete Stock-In [{did}]?  Qty {rec['quantity']} item {rec['item_id']}",reply_markup=kb)
    return SI_DELETE_CONFIRM

@require_unlock
async def confirm_delete_stockin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data!="del_conf_yes":
        await show_stockin_menu(update,context); return ConversationHandler.END
    d=context.user_data["del"]; rec=d["rec"]
    secure_db.remove("partner_inventory",[d["id"]])
    adjust_store_inventory(rec["store_id"],rec["item_id"],-rec["quantity"])
    await update.callback_query.edit_message_text(
        "✅ Stock-In deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="stockin_menu")]]))
    return ConversationHandler.END

# ======================================================================
#                       REGISTER  HANDLERS
# ======================================================================
def register_stockin_handlers(app: Application):
    # Sub-menu
    app.add_handler(CallbackQueryHandler(show_stockin_menu, pattern="^stockin_menu$"))

    # --- Add
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add_stockin",add_stockin),
                      CallbackQueryHandler(add_stockin,pattern="^add_stockin$")],
        states={
            SI_PARTNER_SELECT:[CallbackQueryHandler(get_stockin_partner,pattern="^si_part_\\d+$")],
            SI_STORE_SELECT:  [CallbackQueryHandler(get_stockin_store, pattern="^si_store_\\d+$")],
            SI_ITEM_SELECT:   [MessageHandler(filters.TEXT & ~filters.COMMAND,get_stockin_item)],
            SI_QTY:           [MessageHandler(filters.TEXT & ~filters.COMMAND,get_stockin_qty)],
            SI_COST:          [MessageHandler(filters.TEXT & ~filters.COMMAND,get_stockin_cost)],
            SI_NOTE:          [CallbackQueryHandler(get_stockin_note,pattern="^si_note_skip$"),
                               MessageHandler(filters.TEXT & ~filters.COMMAND,get_stockin_note)],
            SI_DATE:          [CallbackQueryHandler(get_stockin_date,pattern="^si_date_skip$"),
                               MessageHandler(filters.TEXT & ~filters.COMMAND,get_stockin_date)],
            SI_CONFIRM:       [CallbackQueryHandler(confirm_stockin,pattern="^si_conf_")]
        },
        fallbacks=[CommandHandler("cancel",show_stockin_menu)],
        per_message=False))

    # --- View
    app.add_handler(CallbackQueryHandler(view_stockins,pattern="^view_stockin$"))
    app.add_handler(CallbackQueryHandler(view_stockins_filtered,pattern="^stockin_filter_"))
    app.add_handler(CallbackQueryHandler(view_stockins_prev,pattern="^stockin_prev$"))
    app.add_handler(CallbackQueryHandler(view_stockins_next,pattern="^stockin_next$"))

    # --- Edit
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("edit_stockin",edit_stockin),
                      CallbackQueryHandler(edit_stockin,pattern="^edit_stockin$")],
        states={
            SI_EDIT_SELECT:[
                MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_stockin_by_id),
                CallbackQueryHandler(edit_si_filtered,pattern="^edit_si_filter_"),
                CallbackQueryHandler(edit_si_prev,pattern="^edit_si_prev$"),
                CallbackQueryHandler(edit_si_next,pattern="^edit_si_next$")],
            SI_EDIT_QTY:     [MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_qty)],
            SI_EDIT_COST:    [MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_cost)],
            SI_EDIT_DATE:    [CallbackQueryHandler(get_edit_date,pattern="^edate_skip$"),
                              MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_date)],
            SI_EDIT_CONFIRM: [CallbackQueryHandler(confirm_edit_stockin,pattern="^edit_conf_")]
        },
        fallbacks=[CommandHandler("cancel",show_stockin_menu)],
        per_message=False))

    # --- Delete
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("remove_stockin",remove_stockin),
                      CallbackQueryHandler(remove_stockin,pattern="^remove_stockin$")],
        states={
            SI_DELETE_SELECT:[
                MessageHandler(filters.TEXT & ~filters.COMMAND,get_delete_stockin_by_id),
                CallbackQueryHandler(del_si_filtered,pattern="^del_si_filter_"),
                CallbackQueryHandler(del_si_prev,pattern="^del_si_prev$"),
                CallbackQueryHandler(del_si_next,pattern="^del_si_next$")],
            SI_DELETE_CONFIRM:[CallbackQueryHandler(confirm_delete_stockin,pattern="^del_conf_")]
        },
        fallbacks=[CommandHandler("cancel",show_stockin_menu)],
        per_message=False))
