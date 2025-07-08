# handlers/partner_sales.py
# ────────────────────────────────────────────────────────────────
#  Partner-Sales module  (Owner → Partner lump-sum reconciliation)
#  Flattened schema: one record per item, matching sales/stockin patterns
# ────────────────────────────────────────────────────────────────
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
from tinydb import Query

from handlers.utils import require_unlock, fmt_money, fmt_date
from secure_db import secure_db

DEFAULT_CUR = "USD"

def _partner_currency(pid: int) -> str:
    p = secure_db.table("partners").get(doc_id=pid)
    return p.get("currency", DEFAULT_CUR) if p else DEFAULT_CUR

def _filter_by_time(rows: list[dict], period: str) -> list[dict]:
    if period in ("3m", "6m"):
        days = 90 if period=="3m" else 180
        cutoff = datetime.utcnow().timestamp() - days*86400
        return [r for r in rows if datetime.fromisoformat(r["timestamp"]).timestamp() >= cutoff]
    return rows

(
    PS_PARTNER_SELECT, PS_ITEM_ID, PS_ITEM_QTY, PS_ITEM_PRICE,
    PS_NOTE, PS_DATE, PS_CONFIRM,
    PS_VIEW_PARTNER, PS_VIEW_TIME, PS_VIEW_PAGE,
    PS_EDIT_PARTNER, PS_EDIT_TIME, PS_EDIT_PAGE,
    PS_EDIT_FIELD, PS_EDIT_NEWVAL, PS_EDIT_CONFIRM,
    PS_DEL_PARTNER, PS_DEL_TIME, PS_DEL_PAGE, PS_DEL_CONFIRM,
) = range(20)

async def show_partner_sales_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Partner Sale",    callback_data="add_psale")],
        [InlineKeyboardButton("👀 View Partner Sales",  callback_data="view_psale")],
        [InlineKeyboardButton("✏️ Edit Partner Sale",   callback_data="edit_psale")],
        [InlineKeyboardButton("🗑️ Remove Partner Sale", callback_data="del_psale")],
        [InlineKeyboardButton("🔙 Main Menu",           callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text(
        "Partner Sales: choose an action", reply_markup=kb
    )

@require_unlock
async def add_psale_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    parts = secure_db.all("partners")
    if not parts:
        await update.callback_query.edit_message_text(
            "No partners defined.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_sales_menu")]])
        )
        return ConversationHandler.END
    btns = [InlineKeyboardButton(p["name"], callback_data=f"ps_part_{p.doc_id}") for p in parts]
    rows = [btns[i:i+2] for i in range(0,len(btns),2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="partner_sales_menu")])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=InlineKeyboardMarkup(rows))
    return PS_PARTNER_SELECT

async def psale_choose_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["ps_partner"] = pid
    context.user_data["ps_items"]   = {}
    await update.callback_query.edit_message_text("Enter item_id (or type DONE):")
    return PS_ITEM_ID

async def psale_item_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.upper()=="DONE":
        if not context.user_data["ps_items"]:
            await update.message.reply_text("Please enter at least one item before DONE.")
            return PS_ITEM_ID
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="ps_note_skip")]])
        await update.message.reply_text("Optional note (or Skip):", reply_markup=kb)
        return PS_NOTE
    context.user_data["cur_item"] = text
    await update.message.reply_text(f"Quantity for {text}:")
    return PS_ITEM_QTY

async def psale_item_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip()); assert qty!=0
    except:
        await update.message.reply_text("Non-zero integer please.")
        return PS_ITEM_QTY
    context.user_data["cur_qty"] = qty
    await update.message.reply_text(f"Unit price for {context.user_data['cur_item']}:")
    return PS_ITEM_PRICE

async def psale_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
    except:
        await update.message.reply_text("Numeric price please (negatives allowed).")
        return PS_ITEM_PRICE
    iid = context.user_data["cur_item"]
    context.user_data["ps_items"][iid] = {
        "qty": context.user_data["cur_qty"],
        "unit_price": price
    }
    await update.message.reply_text("Enter next item_id (or type DONE):")
    return PS_ITEM_ID

async def psale_get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data=="ps_note_skip":
        await update.callback_query.answer()
        note=""
    else:
        note=update.message.text.strip()
    context.user_data["ps_note"]=note
    today=datetime.now().strftime("%d%m%Y")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip", callback_data="ps_date_skip")]])
    prompt=f"Enter date DDMMYYYY or Skip for today ({today}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return PS_DATE

async def psale_get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data=="ps_date_skip":
        await update.callback_query.answer()
        date_str=datetime.now().strftime("%d%m%Y")
    else:
        date_str=update.message.text.strip()
        try:
            datetime.strptime(date_str,"%d%m%Y")
        except:
            await update.message.reply_text("Format DDMMYYYY, please.")
            return PS_DATE
    context.user_data["ps_date"]=date_str

    # confirm
    pid=context.user_data["ps_partner"]
    pname=secure_db.table("partners").get(doc_id=pid)["name"]
    items=context.user_data["ps_items"]
    cur=_partner_currency(pid)
    lines=[
        f" • {iid} ×{d['qty']} @ {fmt_money(d['unit_price'],cur)} = {fmt_money(d['qty']*d['unit_price'],cur)}"
        for iid,d in items.items()
    ]
    summary=(
        f"✅ **Confirm Partner Sale**\nPartner: {pname}\n\n"
        f"Items:\n" + "\n".join(lines) + "\n\n"
        f"Note: {context.user_data.get('ps_note') or '—'}\n"
        f"Date: {fmt_date(date_str)}\n\nConfirm?"
    )
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="ps_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="ps_conf_no")]
    ])
    await (update.callback_query.edit_message_text if update.callback_query
           else update.message.reply_text)(summary, reply_markup=kb)
    return PS_CONFIRM

@require_unlock
async def psale_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data!="ps_conf_yes":
        await show_partner_sales_menu(update,context)
        return ConversationHandler.END

    d=context.user_data
    pid=d["ps_partner"]
    cur=_partner_currency(pid)
    # insert one row per item
    for iid,det in d["ps_items"].items():
        secure_db.insert("partner_sales",{
            "partner_id": pid,
            "item_id":    iid,
            "quantity":   det["qty"],
            "unit_price": det["unit_price"],
            "currency":   cur,
            "note":       d.get("ps_note",""),
            "date":       d["ps_date"],
            "timestamp":  datetime.utcnow().isoformat(),
        })
    # adjust inventory
    Q=Query()
    for iid,det in d["ps_items"].items():
        row=secure_db.table("partner_inventory").get(
            (Q.partner_id==pid)&(Q.item_id==iid)
        )
        if not row or row["quantity"]<det["qty"]:
            await update.callback_query.edit_message_text(
                f"❌ Error: insufficient stock for {iid}.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_sales_menu")]])
            )
            return ConversationHandler.END
        secure_db.update("partner_inventory",
                         {"quantity": row["quantity"]-det["qty"]},
                         [row.doc_id])
    await update.callback_query.edit_message_text(
        "✅ Partner Sale recorded.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_sales_menu")]])
    )
    return ConversationHandler.END

@require_unlock
async def view_psale_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    parts=secure_db.all("partners")
    btns=[InlineKeyboardButton(p["name"],callback_data=f"ps_view_part_{p.doc_id}") for p in parts]
    btns.append(InlineKeyboardButton("🔙 Back",callback_data="partner_sales_menu"))
    kb=InlineKeyboardMarkup([btns[i:i+2] for i in range(0,len(btns),2)])
    await update.callback_query.edit_message_text("Select partner:",reply_markup=kb)
    return PS_VIEW_PARTNER

async def view_psale_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid=int(update.callback_query.data.split("_")[-1])
    context.user_data["view_pid"]=pid
    context.user_data["view_page"]=1
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 M",callback_data="ps_view_time_3m"),
         InlineKeyboardButton("📅 Last 6 M",callback_data="ps_view_time_6m")],
        [InlineKeyboardButton("🗓️ All", callback_data="ps_view_time_all")],
        [InlineKeyboardButton("🔙 Back",callback_data="view_psale")],
    ])
    await update.callback_query.edit_message_text("Select period:",reply_markup=kb)
    return PS_VIEW_TIME

async def view_psale_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_time"]=update.callback_query.data.split("_")[-1]
    # reuse existing page index
    return await send_psale_view_page(update, context)

async def send_psale_view_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid=context.user_data["view_pid"]
    period=context.user_data["view_time"]
    page=context.user_data.get("view_page",1)
    size=20
    rows=[r for r in secure_db.all("partner_sales") if r["partner_id"]==pid]
    rows=_filter_by_time(rows,period)
    total_pages=max(1,(len(rows)+size-1)//size)
    chunk=rows[(page-1)*size:page*size]
    if not chunk:
        await update.callback_query.edit_message_text(
            "No partner sales in that window.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="view_psale")]])
        )
        return ConversationHandler.END
    lines=[]
    for r in chunk:
        dt=fmt_date(r["date"])
        amt=fmt_money(r["quantity"]*r["unit_price"],r["currency"])
        lines.append(
            f"{r.doc_id}: Item {r['item_id']} ×{r['quantity']}  "
            f"@ {fmt_money(r['unit_price'],r['currency'])} = {amt} on {dt}"
        )
    text=f"📄 **Partner Sales**  P{page}/{total_pages}\n\n"+"\n".join(lines)
    nav=[]
    if page>1: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="ps_view_prev"))
    if page<total_pages: nav.append(InlineKeyboardButton("➡️ Next",callback_data="ps_view_next"))
    nav.append(InlineKeyboardButton("🔙 Back",callback_data="view_psale"))
    await update.callback_query.edit_message_text(text,reply_markup=InlineKeyboardMarkup([nav]))
    return PS_VIEW_PAGE

async def handle_psale_view_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if "prev" in update.callback_query.data:
        context.user_data["view_page"]-=1
    else:
        context.user_data["view_page"]+=1
    return await send_psale_view_page(update, context)

@require_unlock
async def edit_psale_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    parts=secure_db.all("partners")
    btns=[InlineKeyboardButton(p["name"],callback_data=f"ps_edit_part_{p.doc_id}") for p in parts]
    btns.append(InlineKeyboardButton("🔙 Back",callback_data="partner_sales_menu"))
    kb=InlineKeyboardMarkup([btns[i:i+2] for i in range(0,len(btns),2)])
    await update.callback_query.edit_message_text("Select partner:",reply_markup=kb)
    return PS_EDIT_PARTNER

async def edit_psale_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid=int(update.callback_query.data.split("_")[-1])
    context.user_data["edit_pid"]=pid
    context.user_data["edit_page"]=1
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 M",callback_data="ps_edit_time_3m"),
         InlineKeyboardButton("📅 Last 6 M",callback_data="ps_edit_time_6m")],
        [InlineKeyboardButton("🗓️ All",callback_data="ps_edit_time_all")],
        [InlineKeyboardButton("🔙 Back",callback_data="edit_psale")],
    ])
    await update.callback_query.edit_message_text("Select period:",reply_markup=kb)
    return PS_EDIT_TIME

async def edit_psale_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_time"]=update.callback_query.data.split("_")[-1]
    return await send_psale_edit_page(update, context)

async def send_psale_edit_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid=context.user_data["edit_pid"]
    period=context.user_data["edit_time"]
    page=context.user_data.get("edit_page",1)
    size=20
    rows=[r for r in secure_db.all("partner_sales") if r["partner_id"]==pid]
    rows=_filter_by_time(rows,period)
    total_pages=max(1,(len(rows)+size-1)//size)
    chunk=rows[(page-1)*size:page*size]
    if not chunk:
        await update.callback_query.edit_message_text(
            "No records.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="edit_psale")]])
        )
        return ConversationHandler.END
    lines=[]
    for r in chunk:
        dt=fmt_date(r["date"])
        amt=fmt_money(r["quantity"]*r["unit_price"],r["currency"])
        lines.append(
            f"{r.doc_id}: Item {r['item_id']} ×{r['quantity']}  "
            f"@ {fmt_money(r['unit_price'],r['currency'])} = {amt} on {dt}"
        )
    msg=f"✏️ **Edit Partner Sales**  P{page}/{total_pages}\n\n"+"\n".join(lines)+"\n\nReply with record ID or use ⬅️➡️"
    nav=[]
    if page>1: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="ps_edit_prev"))
    if page<total_pages: nav.append(InlineKeyboardButton("➡️ Next",callback_data="ps_edit_next"))
    nav.append(InlineKeyboardButton("🔙 Back",callback_data="edit_psale"))
    await update.callback_query.edit_message_text(msg,reply_markup=InlineKeyboardMarkup([nav]))
    return PS_EDIT_PAGE

async def handle_psale_edit_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if "prev" in update.callback_query.data:
        context.user_data["edit_page"]-=1
    else:
        context.user_data["edit_page"]+=1
    return await send_psale_edit_page(update, context)

async def edit_psale_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sid=int(update.message.text.strip())
    except:
        sid=None
    rec=secure_db.table("partner_sales").get(doc_id=sid) if sid else None
    if not rec or rec["partner_id"]!=context.user_data["edit_pid"]:
        await update.message.reply_text("ID not in this list.")
        return PS_EDIT_PAGE
    context.user_data["edit_sid"]=sid
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("Quantity",callback_data="ps_edit_field_quantity"),
         InlineKeyboardButton("Unit Price",callback_data="ps_edit_field_unit_price")],
        [InlineKeyboardButton("Date",callback_data="ps_edit_field_date"),
         InlineKeyboardButton("Note",callback_data="ps_edit_field_note")],
        [InlineKeyboardButton("🔙 Cancel",callback_data="edit_psale")]
    ])
    await update.message.reply_text(f"Editing record #{sid}. Choose field:",reply_markup=kb)
    return PS_EDIT_FIELD

async def edit_psale_choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    field=update.callback_query.data.split("_")[-1]
    context.user_data["edit_field"]=field
    if field=="date":
        today=datetime.now().strftime("%d%m%Y")
        await update.callback_query.edit_message_text(f"New date DDMMYYYY (today {today}):")
    else:
        await update.callback_query.edit_message_text(f"New {field.replace('_',' ')}:")
    return PS_EDIT_NEWVAL

async def edit_psale_newval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["edit_newval"]=update.message.text.strip()
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes",callback_data="ps_edit_conf_yes"),
         InlineKeyboardButton("❌ No", callback_data="ps_edit_conf_no")]
    ])
    await update.message.reply_text(
        f"Change **{context.user_data['edit_field']}** → `{context.user_data['edit_newval']}`?",
        reply_markup=kb
    )
    return PS_EDIT_CONFIRM

@require_unlock
async def edit_psale_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data!="ps_edit_conf_yes":
        await show_partner_sales_menu(update,context)
        return ConversationHandler.END
    sid=context.user_data["edit_sid"]
    field=context.user_data["edit_field"]
    newv=context.user_data["edit_newval"]
    if field in ("quantity","unit_price","date","note"):
        key = field
        val = int(newv) if field=="quantity" else (float(newv) if field=="unit_price" else newv)
        if field=="note" and newv=="-": val=""
        secure_db.update("partner_sales",{key:val},[sid])
    await update.callback_query.edit_message_text(
        "✅ Partner Sale updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="partner_sales_menu")]])
    )
    return ConversationHandler.END

@require_unlock
async def del_psale_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    parts=secure_db.all("partners")
    btns=[InlineKeyboardButton(p["name"],callback_data=f"ps_del_part_{p.doc_id}") for p in parts]
    btns.append(InlineKeyboardButton("🔙 Back",callback_data="partner_sales_menu"))
    kb=InlineKeyboardMarkup([btns[i:i+2] for i in range(0,len(btns),2)])
    await update.callback_query.edit_message_text("Select partner:",reply_markup=kb)
    return PS_DEL_PARTNER

async def del_psale_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid=int(update.callback_query.data.split("_")[-1])
    context.user_data["del_pid"]=pid
    context.user_data["del_page"]=1
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 M",callback_data="ps_del_time_3m"),
         InlineKeyboardButton("📅 Last 6 M",callback_data="ps_del_time_6m")],
        [InlineKeyboardButton("🗓️ All",callback_data="ps_del_time_all")],
        [InlineKeyboardButton("🔙 Back",callback_data="del_psale")],
    ])
    await update.callback_query.edit_message_text("Select period:",reply_markup=kb)
    return PS_DEL_TIME

async def del_psale_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_time"]=update.callback_query.data.split("_")[-1]
    return await send_psale_del_page(update, context)

async def send_psale_del_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid=context.user_data["del_pid"]
    period=context.user_data["del_time"]
    page=context.user_data.get("del_page",1)
    size=20
    rows=[r for r in secure_db.all("partner_sales") if r["partner_id"]==pid]
    rows=_filter_by_time(rows,period)
    total_pages=max(1,(len(rows)+size-1)//size)
    chunk=rows[(page-1)*size:page*size]
    if not chunk:
        await update.callback_query.edit_message_text(
            "No records.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="del_psale")]])
        )
        return ConversationHandler.END
    lines=[]
    for r in chunk:
        dt=fmt_date(r["date"])
        amt=fmt_money(r["quantity"]*r["unit_price"],r["currency"])
        lines.append(
            f"{r.doc_id}: Item {r['item_id']} ×{r['quantity']}  "
            f"@ {fmt_money(r['unit_price'],r['currency'])} = {amt} on {dt}"
        )
    msg=f"🗑️ **Delete Partner Sales**  P{page}/{total_pages}\n\n"+ "\n".join(lines) + "\n\nReply with record ID or use ⬅️➡️"
    nav=[]
    if page>1: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="ps_del_prev"))
    if page<total_pages: nav.append(InlineKeyboardButton("➡️ Next",callback_data="ps_del_next"))
    nav.append(InlineKeyboardButton("🔙 Back",callback_data="del_psale"))
    await update.callback_query.edit_message_text(msg,reply_markup=InlineKeyboardMarkup([nav]))
    return PS_DEL_PAGE

async def handle_psale_del_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if "prev" in update.callback_query.data:
        context.user_data["del_page"]-=1
    else:
        context.user_data["del_page"]+=1
    return await send_psale_del_page(update, context)

async def del_psale_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sid=int(update.message.text.strip())
    except:
        sid=None
    rec=secure_db.table("partner_sales").get(doc_id=sid) if sid else None
    if not rec or rec["partner_id"]!=context.user_data["del_pid"]:
        await update.message.reply_text("ID not in this list.")
        return PS_DEL_PAGE
    context.user_data["del_sid"]=sid
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes",callback_data="ps_del_conf_yes"),
         InlineKeyboardButton("❌ No", callback_data="ps_del_conf_no")]
    ])
    await update.message.reply_text(f"Delete record #{sid} ?",reply_markup=kb)
    return PS_DEL_CONFIRM

@require_unlock
async def del_psale_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data!="ps_del_conf_yes":
        await show_partner_sales_menu(update,context)
        return ConversationHandler.END
    sid=context.user_data["del_sid"]
    rec=secure_db.table("partner_sales").get(doc_id=sid)
    Q=Query()
    # revert inventory
    for iid,det in [(rec["item_id"],{"qty":rec["quantity"]})]:
        row=secure_db.table("partner_inventory").get(
            (Q.partner_id==rec["partner_id"])&(Q.item_id==iid)
        )
        if row:
            secure_db.update("partner_inventory",
                             {"quantity":row["quantity"]+det["qty"]},
                             [row.doc_id])
    secure_db.remove("partner_sales",[sid])
    await update.callback_query.edit_message_text(
        f"✅ Partner Sale #{sid} deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="partner_sales_menu")]])
    )
    return ConversationHandler.END

def register_partner_sales_handlers(app):
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_psale_start,pattern="^add_psale$"),
                      CommandHandler("add_psale",add_psale_start)],
        states={
            PS_PARTNER_SELECT:[CallbackQueryHandler(psale_choose_partner,pattern="^ps_part_\\d+$")],
            PS_ITEM_ID:[MessageHandler(filters.TEXT & ~filters.COMMAND,psale_item_id)],
            PS_ITEM_QTY:[MessageHandler(filters.TEXT & ~filters.COMMAND,psale_item_qty)],
            PS_ITEM_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND,psale_item_price)],
            PS_NOTE:[CallbackQueryHandler(psale_get_note,pattern="^ps_note_skip$"),
                     MessageHandler(filters.TEXT & ~filters.COMMAND,psale_get_note)],
            PS_DATE:[CallbackQueryHandler(psale_get_date,pattern="^ps_date_skip$"),
                     MessageHandler(filters.TEXT & ~filters.COMMAND,psale_get_date)],
            PS_CONFIRM:[CallbackQueryHandler(psale_confirm,pattern="^ps_conf_")],
        },
        fallbacks=[CommandHandler("cancel",show_partner_sales_menu)],
        per_message=False,
    )
    app.add_handler(add_conv)

    view_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(view_psale_start,pattern="^view_psale$")],
        states={
            PS_VIEW_PARTNER:[CallbackQueryHandler(view_psale_period,pattern="^ps_view_part_\\d+$")],
            PS_VIEW_TIME:[CallbackQueryHandler(view_psale_set_filter,pattern="^ps_view_time_")],
            PS_VIEW_PAGE:[CallbackQueryHandler(handle_psale_view_nav,pattern="^ps_view_(prev|next)$")],
        },
        fallbacks=[CommandHandler("cancel",show_partner_sales_menu)],
        per_message=False,
    )
    app.add_handler(view_conv)

    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_psale_start,pattern="^edit_psale$")],
        states={
            PS_EDIT_PARTNER:[CallbackQueryHandler(edit_psale_period,pattern="^ps_edit_part_\\d+$")],
            PS_EDIT_TIME:[CallbackQueryHandler(edit_psale_set_filter,pattern="^ps_edit_time_")],
            PS_EDIT_PAGE:[
                CallbackQueryHandler(handle_psale_edit_nav,pattern="^ps_edit_(prev|next)$"),
                MessageHandler(filters.Regex(r"^\d+$") & ~filters.COMMAND, edit_psale_pick_doc)
            ],
            PS_EDIT_FIELD:[CallbackQueryHandler(edit_psale_choose_field,pattern="^ps_edit_field_")],
            PS_EDIT_NEWVAL:[MessageHandler(filters.TEXT & ~filters.COMMAND,edit_psale_newval)],
            PS_EDIT_CONFIRM:[CallbackQueryHandler(edit_psale_confirm,pattern="^ps_edit_conf_")],
        },
        fallbacks=[CommandHandler("cancel",show_partner_sales_menu)],
        per_message=False,
    )
    app.add_handler(edit_conv)

    del_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(del_psale_start,pattern="^del_psale$")],
        states={
            PS_DEL_PARTNER:[CallbackQueryHandler(del_psale_period,pattern="^ps_del_part_\\d+$")],
            PS_DEL_TIME:[CallbackQueryHandler(del_psale_set_filter,pattern="^ps_del_time_")],
            PS_DEL_PAGE:[
                CallbackQueryHandler(handle_psale_del_nav,pattern="^ps_del_(prev|next)$"),
                MessageHandler(filters.Regex(r"^\d+$") & ~filters.COMMAND,del_psale_pick_doc)
            ],
            PS_DEL_CONFIRM:[CallbackQueryHandler(del_psale_confirm,pattern="^ps_del_conf_")],
        },
        fallbacks=[CommandHandler("cancel",show_partner_sales_menu)],
        per_message=False,
    )
    app.add_handler(del_conv)
