"""
Payouts module – ledger-linked related_id pattern (2025-07-15).
- Every payout writes to ledger first; gets back a related_id (ledger doc_id).
- The main DB row stores related_id.
- All edits/deletes use related_id for ledger ops.
- All list displays and selections use related_id as the reference number, fallback to doc_id for legacy.
"""

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
from handlers.utils import require_unlock, fmt_money, fmt_date  # helpers
from handlers.ledger import add_ledger_entry, delete_ledger_entries_by_related
from secure_db import secure_db

logger = logging.getLogger("payouts")

# Conversation-state constants
(
    PO_ADD_PARTNER, PO_ADD_LOCAL, PO_ADD_FEE,  PO_ADD_USD,
    PO_ADD_NOTE,    PO_ADD_DATE,  PO_ADD_CONFIRM,

    PO_VIEW_PARTNER, PO_VIEW_TIME, PO_VIEW_PAGE,

    PO_EDIT_PARTNER, PO_EDIT_TIME, PO_EDIT_PAGE,
    PO_EDIT_LOCAL,   PO_EDIT_FEE,  PO_EDIT_USD,
    PO_EDIT_NOTE,    PO_EDIT_DATE, PO_EDIT_CONFIRM,

    PO_DEL_PARTNER,  PO_DEL_TIME,  PO_DEL_PAGE, PO_DEL_CONFIRM,
) = range(23)

ROWS_PER_PAGE = 20

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

def _calc_fx(local_amt: float, fee_amt: float, usd: float) -> float:
    return (local_amt - fee_amt) / usd if usd else 0.0

def _partner_currency(pid: int) -> str:
    row = secure_db.table("partners").get(doc_id=pid) or {}
    return row.get("currency", "USD")

OWNER_ACCOUNT_ID = "POT"

def _ledger_delete_payout(partner_id, related_id):
    # Always use related_id for ledger deletions
    delete_ledger_entries_by_related("partner", partner_id, related_id)
    delete_ledger_entries_by_related("owner", OWNER_ACCOUNT_ID, related_id)

def _ledger_add_payout(partner_id, local_amt, usd_amt, cur, fee_perc, fee_amt, fx, note, date, timestamp):
    """
    Add partner and owner ledger entries for payout.
    Returns: related_id (ledger doc_id) of the partner entry.
    """
    related_id = add_ledger_entry(
        account_type="partner",
        account_id=partner_id,
        entry_type="payment",  # so it shows in partner report
        amount=local_amt,
        currency=cur,
        note=note,
        date=date,
        timestamp=timestamp,
        fee_perc=fee_perc,
        fee_amt=fee_amt,
        fx_rate=fx,
        usd_amt=usd_amt,
        return_id=True,   # must be supported by your ledger module
    )
    add_ledger_entry(
        account_type="owner",
        account_id=OWNER_ACCOUNT_ID,
        entry_type="payout_sent",
        related_id=related_id,
        amount=-usd_amt,
        currency="USD",
        note=f"Payout to partner {partner_id}. {note}",
        date=date,
        timestamp=timestamp,
        fee_perc=fee_perc,
        fee_amt=fee_amt,
        fx_rate=fx,
        usd_amt=usd_amt,
    )
    return related_id

# ────────────────────────────────────────────────────────────
#  Sub-menu  +  universal Back handler
# ────────────────────────────────────────────────────────────
async def show_payout_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Show payout menu")
    if update.callback_query:
        await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Payout",     callback_data="add_payout")],
        [InlineKeyboardButton("👀 View Payouts",   callback_data="view_payout")],
        [InlineKeyboardButton("✏️ Edit Payout",    callback_data="edit_payout")],
        [InlineKeyboardButton("🗑️ Remove Payout", callback_data="remove_payout")],
        [InlineKeyboardButton("🔙 Back",           callback_data="main_menu")],
    ])
    msg = "💸 Payouts: choose an action"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def payout_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Back to payout menu")
    context.user_data.clear()
    await show_payout_menu(update, context)
    return ConversationHandler.END

# ======================================================================
#                              ADD  FLOW
# ======================================================================
@require_unlock
async def add_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Add payout - select partner")
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "⚠️ No partners available.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"po_add_part_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return PO_ADD_PARTNER

async def get_add_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["partner_id"] = int(update.callback_query.data.split("_")[-1])
    await update.callback_query.edit_message_text("Enter local amount to pay:")
    return PO_ADD_LOCAL

async def get_add_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text); assert amt > 0
    except Exception:
        await update.message.reply_text("❌ Positive number please."); return PO_ADD_LOCAL
    context.user_data["local_amt"] = amt
    await update.message.reply_text("Enter handling fee % (e.g. 2.5) or 0 if none:")
    return PO_ADD_FEE

async def get_add_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pct = float(update.message.text); assert 0 <= pct < 100
    except Exception:
        await update.message.reply_text("❌ 0–99 please."); return PO_ADD_FEE
    d = context.user_data
    d["fee_perc"] = pct
    d["fee_amt"]  = d["local_amt"] * pct / 100
    await update.message.reply_text("Enter USD paid:")
    return PO_ADD_USD

async def get_add_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text)
    except Exception:
        await update.message.reply_text("❌ Number please."); return PO_ADD_USD
    context.user_data["usd_amt"] = usd
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="po_add_note_skip")]])
    await update.message.reply_text("Enter optional note or Skip:", reply_markup=kb)
    return PO_ADD_NOTE

async def get_add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = "" if (update.callback_query and update.callback_query.data.endswith("skip")) else update.message.text.strip()
    if update.callback_query:
        await update.callback_query.answer()
    context.user_data["note"] = note
    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="po_add_date_skip")]])
    prompt = f"Enter payout date DDMMYYYY or Skip ({fmt_date(today)}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return PO_ADD_DATE

async def get_add_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date = datetime.now().strftime("%d%m%Y")
    else:
        date = update.message.text.strip()
        try:
            datetime.strptime(date, "%d%m%Y")
        except ValueError:
            await update.message.reply_text("❌ Format DDMMYYYY."); return PO_ADD_DATE
    context.user_data["date"] = date
    return await confirm_add_prompt(update, context)

async def confirm_add_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    cur = _partner_currency(d["partner_id"])
    net = d["local_amt"] - d["fee_amt"]
    fx  = _calc_fx(d["local_amt"], d["fee_amt"], d["usd_amt"])
    summary = (
        f"Local: {fmt_money(d['local_amt'], cur)}\n"
        f"Fee: {d['fee_perc']:.2f}% ({fmt_money(d['fee_amt'], cur)})\n"
        f"USD Paid: {fmt_money(d['usd_amt'], 'USD')}\n"
        f"FX Rate: {fx:.4f}\n"
        f"Note: {d.get('note') or '—'}\n"
        f"Date: {fmt_date(d['date'])}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data="po_add_conf_yes"),
                                InlineKeyboardButton("❌ Cancel",  callback_data="po_add_conf_no")]])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return PO_ADD_CONFIRM

@require_unlock
async def confirm_add_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("no"):
        await payout_back(update, context); return ConversationHandler.END
    d = context.user_data
    cur = _partner_currency(d["partner_id"])
    fx  = _calc_fx(d["local_amt"], d["fee_amt"], d["usd_amt"])
    timestamp = datetime.utcnow().isoformat()
    payout_id = None
    related_id = None
    try:
        # 1️⃣ Write to ledger first, get related_id (the canonical reference number)
        related_id = _ledger_add_payout(
            d["partner_id"], d["local_amt"], d["usd_amt"], cur, d["fee_perc"], d["fee_amt"],
            fx, d.get("note", ""), d["date"], timestamp,
        )
        # 2️⃣ Write payout to DB, saving related_id as the reference number
        payout_id = secure_db.insert("partner_payouts", {
            "partner_id": d["partner_id"],
            "local_amt":  d["local_amt"],
            "fee_perc":   d["fee_perc"],
            "fee_amt":    d["fee_amt"],
            "usd_amt":    d["usd_amt"],
            "fx_rate":    fx,
            "note":       d.get("note", ""),
            "date":       d["date"],
            "timestamp":  timestamp,
            "related_id": related_id,
        })
    except Exception as e:
        logger.error(f"Payout ledger write failed: {e}", exc_info=True)
        # Roll back both ledger and DB insert, if any
        if related_id is not None:
            _ledger_delete_payout(d["partner_id"], related_id)
        if payout_id is not None:
            secure_db.remove("partner_payouts", [payout_id])
        await update.callback_query.edit_message_text(
            "❌ Error: Failed to write payout or ledger. Nothing recorded.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]])
        )
        return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "✅ Payout recorded (ledger updated).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]]))
    return ConversationHandler.END

# ======================================================================
#                          VIEW  FLOW  (Partner → Period → Pages)
# ======================================================================
@require_unlock
async def view_payout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"po_view_part_{p.doc_id}") for p in partners]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="payout_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return PO_VIEW_PARTNER

async def view_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_pid"] = int(update.callback_query.data.split("_")[-1])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M", callback_data="po_view_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M", callback_data="po_view_filt_6m")],
        [InlineKeyboardButton("🗓️ All",     callback_data="po_view_filt_all")],
        [InlineKeyboardButton("🔙 Back",    callback_data="view_payout")]
    ])
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return PO_VIEW_TIME

async def view_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_period"] = update.callback_query.data.split("_")[-1]   # 3m / 6m / all
    context.user_data["view_page"]   = 1
    return await render_view_page(update, context)

async def render_view_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid   = context.user_data["view_pid"]
    period= context.user_data["view_period"]
    page  = context.user_data["view_page"]
    cur   = _partner_currency(pid)

    rows = [r for r in secure_db.all("partner_payouts") if r["partner_id"] == pid]
    if period != "all":
        rows = _months_filter(rows, int(period.rstrip("m")))
    rows.sort(key=lambda r: datetime.strptime(r["date"], "%d%m%Y"), reverse=True)

    total = len(rows)
    start, end = (page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No payouts for that period."
    else:
        lines=[]
        for r in chunk:
            ref = str(r.get('related_id', r.doc_id))
            dt = datetime.strptime(r.get('date','01011970'), "%d%m%Y").strftime("%d/%m/%y") if r.get('date') else "--/--/--"
            lines.append(
                f"{ref}: {dt}: {fmt_money(r['local_amt'], cur)} → {fmt_money(r.get('usd_amt',0),'USD')} "
                f"(fee {r.get('fee_perc',0):.2f}%={fmt_money(r.get('fee_amt',0),cur)})"
            )
        text = f"💸 Payouts  P{page} / {(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n" + "\n".join(lines)
        text += "\n\nReply with reference number (leftmost) or use ⬅️➡️"

    nav=[]
    if start>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="po_view_prev"))
    if end<total: nav.append(InlineKeyboardButton("➡️ Next",callback_data="po_view_next"))
    kb=InlineKeyboardMarkup([nav,[InlineKeyboardButton("🔙 Back",callback_data="view_payout")]])

    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return PO_VIEW_PAGE

async def view_paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_page"] += (-1 if update.callback_query.data.endswith("prev") else 1)
    return await render_view_page(update, context)

# ======================================================================
#                          EDIT  FLOW  (Partner → Period → Pages)
# ======================================================================
@require_unlock
async def edit_payout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"po_edit_part_{p.doc_id}") for p in partners]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="payout_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return PO_EDIT_PARTNER

async def edit_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_pid"]=int(update.callback_query.data.split("_")[-1])
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M",callback_data="po_edit_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M",callback_data="po_edit_filt_6m")],
        [InlineKeyboardButton("🗓️ All",    callback_data="po_edit_filt_all")],
        [InlineKeyboardButton("🔙 Back",   callback_data="edit_payout")]])
    await update.callback_query.edit_message_text("Choose period:",reply_markup=kb)
    return PO_EDIT_TIME

async def edit_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_period"]=update.callback_query.data.split("_")[-1]
    context.user_data["edit_page"]=1
    return await render_edit_page(update,context)

async def render_edit_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid=context.user_data["edit_pid"]; period=context.user_data["edit_period"]; page=context.user_data["edit_page"]
    cur=_partner_currency(pid)
    rows=[r for r in secure_db.all("partner_payouts") if r["partner_id"]==pid]
    if period!="all": rows=_months_filter(rows,int(period.rstrip("m")))
    rows.sort(key=lambda r:datetime.strptime(r["date"],"%d%m%Y"),reverse=True)
    total=len(rows); start,end=(page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk=rows[start:end]
    if not chunk: text="No payouts."
    else:
        lines=[]
        for r in chunk:
            ref = str(r.get('related_id', r.doc_id))
            dt = datetime.strptime(r.get('date','01011970'), "%d%m%Y").strftime("%d/%m/%y") if r.get('date') else "--/--/--"
            lines.append(f"{ref}: {dt}: {fmt_money(r['local_amt'],cur)} → {fmt_money(r.get('usd_amt',0),'USD')}")
        text=(f"✏️ Edit Payouts  P{page}/{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
              + "\n".join(lines)
              + "\n\nReply with reference number (leftmost) or use ⬅️➡️")
    nav=[]
    if start>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="po_edit_prev"))
    if end<total: nav.append(InlineKeyboardButton("➡️ Next",callback_data="po_edit_next"))
    kb=InlineKeyboardMarkup([nav,[InlineKeyboardButton("🔙 Back",callback_data="edit_payout")]])
    await update.callback_query.edit_message_text(text,reply_markup=kb)
    return PO_EDIT_PAGE

async def edit_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_page"] += (-1 if update.callback_query.data.endswith("prev") else 1)
    return await render_edit_page(update,context)

async def edit_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    q = Query()
    # First try related_id, then fallback to doc_id (legacy)
    recs = secure_db.table("partner_payouts").search(q.related_id == user_input)
    rec = recs[0] if recs else secure_db.table("partner_payouts").get(doc_id=int(user_input))  # fallback
    if not rec or rec["partner_id"] != context.user_data["edit_pid"]:
        await update.message.reply_text("❌ Invalid reference number; try again:"); return PO_EDIT_PAGE
    context.user_data.update({
        "edit_rec":  rec,
        "local_amt": rec["local_amt"],
        "fee_perc":  rec.get("fee_perc", 0),
        "fee_amt":   rec.get("fee_amt", 0),
        "usd_amt":   rec.get("usd_amt", 0),
        "note":      rec.get("note", ""),
        "date":      rec.get("date", datetime.now().strftime("%d%m%Y")),
    })
    await update.message.reply_text("New local amount:"); return PO_EDIT_LOCAL

# (continues with edit, delete flows...)

async def edit_new_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text); assert amt > 0
    except Exception:
        await update.message.reply_text("Positive number please."); return PO_EDIT_LOCAL
    context.user_data["local_amt"] = amt
    await update.message.reply_text("New handling fee % (0–99):"); return PO_EDIT_FEE

async def edit_new_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pct = float(update.message.text); assert 0 <= pct < 100
    except Exception:
        await update.message.reply_text("0–99 please."); return PO_EDIT_FEE
    d = context.user_data
    d["fee_perc"] = pct
    d["fee_amt"]  = d["local_amt"] * pct / 100
    await update.message.reply_text("New USD paid:"); return PO_EDIT_USD

async def edit_new_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text)
    except Exception:
        await update.message.reply_text("Number please."); return PO_EDIT_USD
    context.user_data["usd_amt"] = usd
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="po_edit_note_skip")]])
    await update.message.reply_text("New note or Skip:", reply_markup=kb)
    return PO_EDIT_NOTE

async def edit_new_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = "" if (update.callback_query and update.callback_query.data.endswith("skip")) else update.message.text.strip()
    if update.callback_query:
        await update.callback_query.answer()
    context.user_data["note"] = note
    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip", callback_data="po_edit_date_skip")]])
    await update.message.reply_text(f"New date DDMMYYYY or Skip ({fmt_date(today)}):", reply_markup=kb)
    return PO_EDIT_DATE

async def edit_new_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date=datetime.now().strftime("%d%m%Y")
    else:
        date=update.message.text.strip()
        try:
            datetime.strptime(date,"%d%m%Y")
        except ValueError:
            await update.message.reply_text("Format DDMMYYYY."); return PO_EDIT_DATE
    context.user_data["date"]=date
    d=context.user_data; cur=_partner_currency(context.user_data["edit_pid"])
    net = d["local_amt"] - d["fee_amt"]
    fx  = _calc_fx(d["local_amt"], d["fee_amt"], d["usd_amt"])
    summary = (f"Local: {fmt_money(d['local_amt'],cur)}\n"
               f"Fee: {d['fee_perc']:.2f}% ({fmt_money(d['fee_amt'],cur)})\n"
               f"USD Paid: {fmt_money(d['usd_amt'],'USD')}\n"
               f"FX Rate: {fx:.4f}\n"
               f"Note: {d.get('note') or '—'}\n"
               f"Date: {fmt_date(d['date'])}\n\nSave?")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Save",callback_data="po_edit_conf_yes"),
                              InlineKeyboardButton("❌ Cancel",callback_data="po_edit_conf_no")]])
    await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)(
        summary,reply_markup=kb)
    return PO_EDIT_CONFIRM

@require_unlock
async def edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("_no"):
        await payout_back(update, context); return ConversationHandler.END
    rec=context.user_data["edit_rec"]; d=context.user_data
    cur = _partner_currency(rec["partner_id"])
    net = d["local_amt"] - d["fee_amt"]
    fx  = _calc_fx(d["local_amt"], d["fee_amt"], d["usd_amt"])
    related_id = str(rec.get('related_id', rec.doc_id))
    try:
        # --- LEDGER REMOVE old entries ---
        _ledger_delete_payout(rec["partner_id"], related_id)
        # --- Update payout record ---
        secure_db.update("partner_payouts",{
            "local_amt": d["local_amt"],
            "fee_perc":  d["fee_perc"],
            "fee_amt":   d["fee_amt"],
            "usd_amt":   d["usd_amt"],
            "fx_rate":   fx,
            "note":      d.get("note", ""),
            "date":      d["date"],
            "related_id": related_id,
            "timestamp": rec.get("timestamp", datetime.utcnow().isoformat()),
        }, [rec.doc_id])
        # --- LEDGER ADD new ---
        _ledger_add_payout(
            partner_id=rec["partner_id"],
            payout_id=related_id,
            local_amt=d["local_amt"],
            usd_amt=d["usd_amt"],
            cur=cur,
            fee_perc=d["fee_perc"],
            fee_amt=d["fee_amt"],
            fx=fx,
            note=d.get("note", ""),
            date=d["date"],
            timestamp=rec.get("timestamp", datetime.utcnow().isoformat())
        )
    except Exception as e:
        logger.error(f"Edit payout failed, rolling back: {e}", exc_info=True)
        await update.callback_query.edit_message_text(
            "❌ Edit failed: ledger/database error.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payout_menu")]])
        )
        return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "✅ Payout updated (ledger synced).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payout_menu")]]))
    return ConversationHandler.END

# ======================================================================
#                          DELETE  FLOW  (Partner → Period → Pages)
# ======================================================================
@require_unlock
async def del_payout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"po_del_part_{p.doc_id}") for p in partners]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="payout_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return PO_DEL_PARTNER

async def del_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_pid"]=int(update.callback_query.data.split("_")[-1])
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M",callback_data="po_del_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M",callback_data="po_del_filt_6m")],
        [InlineKeyboardButton("🗓️ All",    callback_data="po_del_filt_all")],
        [InlineKeyboardButton("🔙 Back",   callback_data="remove_payout")]])
    await update.callback_query.edit_message_text("Choose period:",reply_markup=kb)
    return PO_DEL_TIME

async def del_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_period"]=update.callback_query.data.split("_")[-1]
    context.user_data["del_page"]=1
    return await render_del_page(update,context)

async def render_del_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid=context.user_data["del_pid"]; period=context.user_data["del_period"]; page=context.user_data["del_page"]
    cur=_partner_currency(pid)
    rows=[r for r in secure_db.all("partner_payouts") if r["partner_id"]==pid]
    if period!="all": rows=_months_filter(rows,int(period.rstrip("m")))
    rows.sort(key=lambda r:datetime.strptime(r["date"],"%d%m%Y"),reverse=True)
    total=len(rows); start,end=(page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk=rows[start:end]
    if not chunk: text="No payouts."
    else:
        lines=[]
        for r in chunk:
            ref = str(r.get('related_id', r.doc_id))
            dt = datetime.strptime(r.get('date','01011970'), "%d%m%Y").strftime("%d/%m/%y") if r.get('date') else "--/--/--"
            lines.append(f"{ref}: {dt}: {fmt_money(r['local_amt'],cur)} → {fmt_money(r.get('usd_amt',0),'USD')}")
        text=(f"🗑️ Delete Payouts  P{page}/{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
              + "\n".join(lines)
              + "\n\nReply with reference number (leftmost) or use ⬅️➡️")
    nav=[]
    if start>0: nav.append(InlineKeyboardButton("⬅️ Prev",callback_data="po_del_prev"))
    if end<total: nav.append(InlineKeyboardButton("➡️ Next",callback_data="po_del_next"))
    kb=InlineKeyboardMarkup([nav,[InlineKeyboardButton("🔙 Back",callback_data="remove_payout")]])
    await update.callback_query.edit_message_text(text,reply_markup=kb)
    return PO_DEL_PAGE

async def del_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_page"] += (-1 if update.callback_query.data.endswith("prev") else 1)
    return await render_del_page(update,context)

async def del_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    q = Query()
    recs = secure_db.table("partner_payouts").search(q.related_id == user_input)
    rec = recs[0] if recs else secure_db.table("partner_payouts").get(doc_id=int(user_input))
    if not rec or rec["partner_id"] != context.user_data["del_pid"]:
        await update.message.reply_text("❌ Invalid reference number; try again:"); return PO_DEL_PAGE
    context.user_data["del_rec"]=rec
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes",callback_data="po_del_conf_yes"),
                              InlineKeyboardButton("❌ No", callback_data="po_del_conf_no")]])
    await update.message.reply_text(f"Delete Payout [{rec.get('related_id', rec.doc_id)}]?",reply_markup=kb)
    return PO_DEL_CONFIRM

@require_unlock
async def del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("_no"):
        await payout_back(update, context); return ConversationHandler.END
    rec=context.user_data["del_rec"]
    related_id = str(rec.get('related_id', rec.doc_id))
    try:
        _ledger_delete_payout(rec["partner_id"], related_id)
        secure_db.remove("partner_payouts",[rec.doc_id])
    except Exception as e:
        logger.error(f"Payout delete failed: {e}", exc_info=True)
        await update.callback_query.edit_message_text(
            "❌ Payout delete failed: ledger/database error.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payout_menu")]])
        )
        return ConversationHandler.END
    await update.callback_query.edit_message_text(
        "✅ Payout deleted (ledger updated).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payout_menu")]]))
    return ConversationHandler.END


# ======================================================================
#                      REGISTER  ALL  HANDLERS
# ======================================================================
def register_payout_handlers(app: Application):
    """Attach Payout submenu + all conversations to the Telegram app."""

    app.add_handler(CallbackQueryHandler(show_payout_menu, pattern="^payout_menu$"))

    # ─────────────────────────── View conversation ───────────────────────────
    view_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(view_payout_start, pattern="^view_payout$")],
        states={
            PO_VIEW_PARTNER: [
                CallbackQueryHandler(view_choose_period, pattern="^po_view_part_\\d+$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_VIEW_TIME: [
                CallbackQueryHandler(view_set_filter,    pattern="^po_view_filt_"),
                CallbackQueryHandler(view_payout_start,  pattern="^view_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_VIEW_PAGE: [
                CallbackQueryHandler(view_paginate,      pattern="^po_view_(prev|next)$"),
                CallbackQueryHandler(view_payout_start,  pattern="^view_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", payout_back)],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(view_conv)

    # ─────────────────────────── Edit conversation ───────────────────────────
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_payout_start, pattern="^edit_payout$")],
        states={
            PO_EDIT_PARTNER: [
                CallbackQueryHandler(edit_choose_period, pattern="^po_edit_part_\\d+$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_EDIT_TIME: [
                CallbackQueryHandler(edit_set_filter,    pattern="^po_edit_filt_"),
                CallbackQueryHandler(edit_payout_start,  pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_EDIT_PAGE: [
                CallbackQueryHandler(edit_page_nav,      pattern="^po_edit_(prev|next)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_pick_doc),
                CallbackQueryHandler(edit_payout_start,  pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_EDIT_LOCAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_local),
                CallbackQueryHandler(edit_payout_start,  pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_EDIT_FEE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_fee),
                CallbackQueryHandler(edit_payout_start,  pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_EDIT_USD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_usd),
                CallbackQueryHandler(edit_payout_start,  pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_EDIT_NOTE: [
                CallbackQueryHandler(edit_new_note,      pattern="^po_edit_note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_note),
                CallbackQueryHandler(edit_payout_start,  pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_EDIT_DATE: [
                CallbackQueryHandler(edit_new_date,      pattern="^po_edit_date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_date),
                CallbackQueryHandler(edit_payout_start,  pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_EDIT_CONFIRM: [
                CallbackQueryHandler(edit_save,          pattern="^po_edit_conf_"),
                CallbackQueryHandler(edit_payout_start,  pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", payout_back)],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(edit_conv)

    # ─────────────────────────── Delete conversation ──────────────────────────
    del_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(del_payout_start, pattern="^remove_payout$")],
        states={
            PO_DEL_PARTNER: [
                CallbackQueryHandler(del_choose_period,  pattern="^po_del_part_\\d+$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_DEL_TIME: [
                CallbackQueryHandler(del_set_filter,     pattern="^po_del_filt_"),
                CallbackQueryHandler(del_payout_start,   pattern="^remove_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_DEL_PAGE: [
                CallbackQueryHandler(del_page_nav,       pattern="^po_del_(prev|next)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, del_pick_doc),
                CallbackQueryHandler(del_payout_start,   pattern="^remove_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
            PO_DEL_CONFIRM: [
                CallbackQueryHandler(del_confirm,        pattern="^po_del_conf_"),
                CallbackQueryHandler(del_payout_start,   pattern="^remove_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", payout_back)],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(del_conv)

    # Add-flow ConversationHandler (unchanged; re-entry not needed)
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_payout", add_payout),
            CallbackQueryHandler(add_payout, pattern="^add_payout$")
        ],
        states={
            PO_ADD_PARTNER: [
                CallbackQueryHandler(get_add_partner, pattern="^po_add_part_\\d+$"),
                CallbackQueryHandler(payout_back,     pattern="^payout_menu$"),
            ],
            PO_ADD_LOCAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_local),
                CallbackQueryHandler(payout_back,     pattern="^payout_menu$"),
            ],
            PO_ADD_FEE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_fee),
                CallbackQueryHandler(payout_back,     pattern="^payout_menu$"),
            ],
            PO_ADD_USD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_usd),
                CallbackQueryHandler(payout_back,     pattern="^payout_menu$"),
            ],
            PO_ADD_NOTE: [
                CallbackQueryHandler(get_add_note, pattern="^po_add_note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_note),
                CallbackQueryHandler(payout_back,  pattern="^payout_menu$"),
            ],
            PO_ADD_DATE: [
                CallbackQueryHandler(get_add_date, pattern="^po_add_date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_date),
                CallbackQueryHandler(payout_back,  pattern="^payout_menu$"),
            ],
            PO_ADD_CONFIRM: [
                CallbackQueryHandler(confirm_add_payout, pattern="^po_add_conf_"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", payout_back)],
        per_message=False,
    )
    app.add_handler(add_conv)
