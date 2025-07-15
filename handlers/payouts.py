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
from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import add_ledger_entry, delete_ledger_entries_by_related
from secure_db import secure_db

logger = logging.getLogger("payouts")

OWNER_ACCOUNT_ID = "POT"

# Conversation-state constants
(
    PO_ADD_PARTNER, PO_ADD_LOCAL, PO_ADD_FEE,  PO_ADD_USD,
    PO_ADD_NOTE,    PO_ADD_DATE,  PO_ADD_CONFIRM,

    PO_VIEW_PARTNER, PO_VIEW_TIME, PO_VIEW_PAGE,

    PO_EDIT_PARTNER, PO_EDIT_TIME, PO_EDIT_PAGE,
    PO_EDIT_FIELD,   PO_EDIT_CONFIRM,

    PO_DEL_PARTNER,  PO_DEL_TIME,  PO_DEL_PAGE, PO_DEL_CONFIRM,
) = range(19)

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
#                              ADD  FLOW (sales-style)
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
    ledger_related_id = None
    try:
        # 1️⃣ Write partner ledger entry FIRST, get unique related_id
        ledger_related_id = add_ledger_entry(
            account_type="partner",
            account_id=d["partner_id"],
            entry_type="payment",
            related_id=None,
            amount=d["local_amt"],
            currency=cur,
            note=d.get("note", ""),
            date=d["date"],
            timestamp=timestamp,
            fee_perc=d["fee_perc"],
            fee_amt=d["fee_amt"],
            fx_rate=fx,
            usd_amt=d["usd_amt"],
        )
        # 2️⃣ Write owner's ledger entry, link with same related_id
        add_ledger_entry(
            account_type="owner",
            account_id=OWNER_ACCOUNT_ID,
            entry_type="payout_sent",
            related_id=ledger_related_id,
            amount=-d["usd_amt"],
            currency="USD",
            note=f"Payout to partner {d['partner_id']}. {d.get('note', '')}",
            date=d["date"],
            timestamp=timestamp,
            fee_perc=d["fee_perc"],
            fee_amt=d["fee_amt"],
            fx_rate=fx,
            usd_amt=d["usd_amt"],
        )
        # 3️⃣ Write payout row in DB, store related_id for future UI/edits
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
            "related_id": ledger_related_id,
        })
    except Exception as e:
        logger.error(f"Payout ledger write failed: {e}", exc_info=True)
        # Roll back ledger and DB insert if any
        if ledger_related_id is not None:
            delete_ledger_entries_by_related("partner", d["partner_id"], ledger_related_id)
            delete_ledger_entries_by_related("owner", OWNER_ACCOUNT_ID, ledger_related_id)
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
                f"{ref}: {dt}: {fmt_money(r['local_amt'], cur)} → {fmt_money(r.get('usd_amt',0), 'USD')} "
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
    try:
        rid = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌ Enter numeric reference number.")
        return PO_EDIT_PAGE
    q = Query()
    # Search using related_id, fallback to doc_id for legacy records
    rec = secure_db.table("partner_payouts").get((q.related_id == rid) | (q.doc_id == rid))
    if not rec or rec["partner_id"] != context.user_data["edit_pid"]:
        await update.message.reply_text("❌ Invalid reference number; try again:")
        return PO_EDIT_PAGE
    context.user_data["edit_rec"] = rec
    context.user_data["edit_related_id"] = rec.get("related_id", rec.doc_id)
    context.user_data["edit_doc_id"] = rec.doc_id

    # Prompt user for field to edit
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Local Amount", callback_data="edit_local_amt")],
        [InlineKeyboardButton("Fee %",        callback_data="edit_fee_perc")],
        [InlineKeyboardButton("USD Paid",     callback_data="edit_usd_amt")],
        [InlineKeyboardButton("Note",         callback_data="edit_note")],
        [InlineKeyboardButton("Date",         callback_data="edit_date")],
        [InlineKeyboardButton("❌ Cancel",     callback_data="edit_cancel")],
    ])
    await update.message.reply_text("Select field to edit:", reply_markup=kb)
    return PO_EDIT_FIELD

async def edit_field_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    action = update.callback_query.data
    context.user_data["edit_field"] = action.replace("edit_", "")
    prompts = {
        "local_amt": "Enter new local amount:",
        "fee_perc": "Enter new fee percent (0-99):",
        "usd_amt": "Enter new USD amount paid:",
        "note": "Enter new note (or leave blank):",
        "date": "Enter new date (DDMMYYYY):",
    }
    if action == "edit_cancel":
        await show_payout_menu(update, context)
        return ConversationHandler.END
    await update.callback_query.edit_message_text(prompts[context.user_data["edit_field"]])
    return PO_EDIT_CONFIRM

async def edit_save_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    field = context.user_data["edit_field"]
    rec = context.user_data["edit_rec"]
    doc_id = rec.doc_id
    related_id = rec.get("related_id", rec.doc_id)
    partner_id = rec["partner_id"]

    # Prepare update dict
    update_fields = {}
    cur = _partner_currency(partner_id)

    # Validate and update only the selected field
    if field == "local_amt":
        try:
            update_fields["local_amt"] = float(value)
        except:
            await update.message.reply_text("❌ Number required. Try again:"); return PO_EDIT_CONFIRM
    elif field == "fee_perc":
        try:
            pct = float(value); assert 0 <= pct < 100
            update_fields["fee_perc"] = pct
            update_fields["fee_amt"] = rec["local_amt"] * pct / 100
        except:
            await update.message.reply_text("❌ 0–99 required. Try again:"); return PO_EDIT_CONFIRM
    elif field == "usd_amt":
        try:
            update_fields["usd_amt"] = float(value)
        except:
            await update.message.reply_text("❌ Number required. Try again:"); return PO_EDIT_CONFIRM
    elif field == "note":
        update_fields["note"] = value
    elif field == "date":
        try:
            datetime.strptime(value, "%d%m%Y")
            update_fields["date"] = value
        except:
            await update.message.reply_text("❌ Format is DDMMYYYY. Try again:"); return PO_EDIT_CONFIRM

    # Recalculate fx and fee_amt if relevant fields were changed
    new_local = update_fields.get("local_amt", rec["local_amt"])
    new_fee = update_fields.get("fee_amt", rec.get("fee_amt", 0))
    new_usd = update_fields.get("usd_amt", rec["usd_amt"])
    new_fx = (new_local - new_fee) / new_usd if new_usd else 0
    update_fields["fx_rate"] = new_fx

    # Confirmation
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Save", callback_data="edit_save_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="edit_save_no")],
    ])
    summary = (
        f"Save new value for {field}?\n"
        f"Local: {fmt_money(new_local, cur)} | Fee: {fmt_money(new_fee, cur)} | USD: {fmt_money(new_usd, 'USD')} | FX: {new_fx:.4f}"
    )
    await update.message.reply_text(summary, reply_markup=kb)
    context.user_data["update_fields"] = update_fields
    return PO_EDIT_CONFIRM

@require_unlock
async def edit_save_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("no"):
        await show_payout_menu(update, context)
        return ConversationHandler.END

    rec = context.user_data["edit_rec"]
    doc_id = rec.doc_id
    related_id = rec.get("related_id", rec.doc_id)
    partner_id = rec["partner_id"]
    update_fields = context.user_data["update_fields"]

    # Remove old ledger entries
    delete_ledger_entries_by_related("partner", partner_id, related_id)
    delete_ledger_entries_by_related("owner", OWNER_ACCOUNT_ID, related_id)

    # Update DB
    secure_db.update("partner_payouts", update_fields, [doc_id])

    # Insert new ledger entries
    cur = _partner_currency(partner_id)
    payout = secure_db.table("partner_payouts").get(doc_id=doc_id)
    try:
        # Partner ledger entry
        add_ledger_entry(
            account_type="partner",
            account_id=partner_id,
            entry_type="payment",
            related_id=related_id,
            amount=payout["local_amt"],
            currency=cur,
            note=payout.get("note", ""),
            date=payout.get("date", ""),
            timestamp=payout.get("timestamp", ""),
            fee_perc=payout.get("fee_perc", 0),
            fee_amt=payout.get("fee_amt", 0),
            fx_rate=payout.get("fx_rate", 0),
            usd_amt=payout.get("usd_amt", 0),
        )
        # Owner ledger entry
        add_ledger_entry(
            account_type="owner",
            account_id=OWNER_ACCOUNT_ID,
            entry_type="payout_sent",
            related_id=related_id,
            amount=-payout["usd_amt"],
            currency="USD",
            note=f"Payout to partner {partner_id}. {payout.get('note', '')}",
            date=payout.get("date", ""),
            timestamp=payout.get("timestamp", ""),
            fee_perc=payout.get("fee_perc", 0),
            fee_amt=payout.get("fee_amt", 0),
            fx_rate=payout.get("fx_rate", 0),
            usd_amt=payout.get("usd_amt", 0),
        )
        await update.callback_query.edit_message_text("✅ Payout updated.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]]))
    except Exception as e:
        logger.error(f"Failed to update payout: {e}")
        await update.callback_query.edit_message_text(f"❌ Error: Failed to update payout: {e}")
    return ConversationHandler.END


# ======================================================================
#                          DELETE  FLOW  (Partner → Period → Pages)
# ======================================================================
@require_unlock
async def remove_payout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p["name"], callback_data=f"po_del_part_{p.doc_id}") for p in partners]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="payout_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
    return PO_DEL_PARTNER

async def del_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_pid"] = int(update.callback_query.data.split("_")[-1])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M", callback_data="po_del_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M", callback_data="po_del_filt_6m")],
        [InlineKeyboardButton("🗓️ All",     callback_data="po_del_filt_all")],
        [InlineKeyboardButton("🔙 Back",    callback_data="remove_payout")]
    ])
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return PO_DEL_TIME

async def del_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_period"] = update.callback_query.data.split("_")[-1]
    context.user_data["del_page"] = 1
    return await render_del_page(update, context)

async def render_del_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data["del_pid"]
    period = context.user_data["del_period"]
    page = context.user_data["del_page"]
    cur = _partner_currency(pid)

    rows = [r for r in secure_db.all("partner_payouts") if r["partner_id"] == pid]
    if period != "all":
        rows = _months_filter(rows, int(period.rstrip("m")))
    rows.sort(key=lambda r: datetime.strptime(r["date"], "%d%m%Y"), reverse=True)

    total = len(rows)
    start, end = (page - 1) * ROWS_PER_PAGE, page * ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No payouts to remove for that period."
    else:
        lines = []
        for r in chunk:
            ref = str(r.get('related_id', r.doc_id))
            dt = datetime.strptime(r.get('date', '01011970'), "%d%m%Y").strftime("%d/%m/%y") if r.get('date') else "--/--/--"
            lines.append(
                f"{ref}: {dt}: {fmt_money(r['local_amt'], cur)} → {fmt_money(r.get('usd_amt', 0), 'USD')}"
            )
        text = f"🗑️ Remove Payouts  P{page}/{(total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE}\n\n" + "\n".join(lines)
        text += "\n\nReply with reference number (leftmost) or use ⬅️➡️"

    nav = []
    if start > 0: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="po_del_prev"))
    if end < total: nav.append(InlineKeyboardButton("➡️ Next", callback_data="po_del_next"))
    kb = InlineKeyboardMarkup([nav, [InlineKeyboardButton("🔙 Back", callback_data="remove_payout")]])

    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return PO_DEL_PAGE

async def del_paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("prev"):
        context.user_data["del_page"] -= 1
    elif update.callback_query.data.endswith("next"):
        context.user_data["del_page"] += 1
    return await render_del_page(update, context)

async def del_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rid = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌ Enter numeric reference number.")
        return PO_DEL_PAGE

    q = Query()
    # Search by related_id or doc_id (legacy)
    rec = secure_db.table("partner_payouts").get((q.related_id == rid) | (q.doc_id == rid))
    if not rec or rec["partner_id"] != context.user_data["del_pid"]:
        await update.message.reply_text("❌ Invalid reference number; try again:")
        return PO_DEL_PAGE

    context.user_data["del_rec"] = rec
    context.user_data["del_related_id"] = rec.get("related_id", rec.doc_id)
    context.user_data["del_doc_id"] = rec.doc_id

    # ...continue with your confirmation prompt...


    cur = _partner_currency(rec["partner_id"])
    dt = datetime.strptime(rec.get('date', '01011970'), "%d%m%Y").strftime("%d/%m/%y") if rec.get('date') else "--/--/--"
    confirm = (
        f"🗑️ Confirm DELETE:\n"
        f"{rec.get('related_id', rec.doc_id)}: {dt}: {fmt_money(rec['local_amt'], cur)} → {fmt_money(rec.get('usd_amt', 0), 'USD')}\n\n"
        "Are you sure?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, delete", callback_data="po_del_conf_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="po_del_conf_no")]
    ])
    await update.message.reply_text(confirm, reply_markup=kb)
    return PO_DEL_CONFIRM

@require_unlock
async def confirm_delete_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("no"):
        await payout_back(update, context)
        return ConversationHandler.END

    rec = context.user_data["del_rec"]
    related_id = rec.get("related_id", rec.doc_id)
    partner_id = rec["partner_id"]
    doc_id = rec.doc_id

    try:
        # Remove from ledger (both partner and owner accounts)
        delete_ledger_entries_by_related("partner", partner_id, related_id)
        delete_ledger_entries_by_related("owner", OWNER_ACCOUNT_ID, related_id)
        # Remove payout row
        secure_db.remove("partner_payouts", [doc_id])
        await update.callback_query.edit_message_text("✅ Payout deleted.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]]))
    except Exception as e:
        logger.error(f"Failed to delete payout: {e}")
        await update.callback_query.edit_message_text(f"❌ Error: Failed to delete payout: {e}")
    return ConversationHandler.END


# ======================================================================
#                      REGISTER  ALL  HANDLERS
# ======================================================================
def register_payout_handlers(app: Application):
    """Attach Payout submenu + all conversations to the Telegram app."""

    # Main menu
    app.add_handler(CallbackQueryHandler(show_payout_menu, pattern="^payout_menu$"))

    # ----------- Add payout -------------
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_payout", add_payout),
            CallbackQueryHandler(add_payout, pattern="^add_payout$")
        ],
        states={
            PO_ADD_PARTNER: [CallbackQueryHandler(get_add_partner, pattern="^po_add_part_\\d+$"),
                             CallbackQueryHandler(payout_back, pattern="^payout_menu$")],
            PO_ADD_LOCAL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_local),
                             CallbackQueryHandler(payout_back, pattern="^payout_menu$")],
            PO_ADD_FEE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_fee),
                             CallbackQueryHandler(payout_back, pattern="^payout_menu$")],
            PO_ADD_USD:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_usd),
                             CallbackQueryHandler(payout_back, pattern="^payout_menu$")],
            PO_ADD_NOTE: [
                CallbackQueryHandler(get_add_note, pattern="^po_add_note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_note),
                CallbackQueryHandler(payout_back, pattern="^payout_menu$")
            ],
            PO_ADD_DATE: [
                CallbackQueryHandler(get_add_date, pattern="^po_add_date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_date),
                CallbackQueryHandler(payout_back, pattern="^payout_menu$")
            ],
            PO_ADD_CONFIRM: [
                CallbackQueryHandler(confirm_add_payout, pattern="^po_add_conf_"),
                CallbackQueryHandler(payout_back, pattern="^payout_menu$")
            ],
        },
        fallbacks=[CommandHandler("cancel", payout_back)],
        per_message=False,
    )
    app.add_handler(add_conv)

    # ----------- View payout -------------
    view_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(view_payout_start, pattern="^view_payout$")],
        states={
            PO_VIEW_PARTNER: [CallbackQueryHandler(view_choose_period, pattern="^po_view_part_\\d+$"),
                              CallbackQueryHandler(payout_back, pattern="^payout_menu$")],
            PO_VIEW_TIME:    [CallbackQueryHandler(view_set_filter, pattern="^po_view_filt_"),
                              CallbackQueryHandler(view_payout_start, pattern="^view_payout$"),
                              CallbackQueryHandler(payout_back, pattern="^payout_menu$")],
            PO_VIEW_PAGE: [
                CallbackQueryHandler(view_paginate, pattern="^po_view_(prev|next)$"),
                CallbackQueryHandler(view_payout_start, pattern="^view_payout$"),
                CallbackQueryHandler(payout_back, pattern="^payout_menu$")
            ],
        },
        fallbacks=[CommandHandler("cancel", payout_back)],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(view_conv)

    # ----------- Edit payout -------------
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_payout_start, pattern="^edit_payout$")],
        states={
            PO_EDIT_PARTNER: [CallbackQueryHandler(edit_choose_period, pattern="^po_edit_part_\\d+$"),
                              CallbackQueryHandler(payout_back, pattern="^payout_menu$")],
            PO_EDIT_TIME:    [CallbackQueryHandler(edit_set_filter, pattern="^po_edit_filt_"),
                              CallbackQueryHandler(edit_payout_start, pattern="^edit_payout$"),
                              CallbackQueryHandler(payout_back, pattern="^payout_menu$")],
            PO_EDIT_PAGE: [
                CallbackQueryHandler(edit_page_nav, pattern="^po_edit_(prev|next)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_pick_doc),
                CallbackQueryHandler(edit_payout_start, pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back, pattern="^payout_menu$")
            ],
            PO_EDIT_FIELD: [CallbackQueryHandler(edit_field_select)],
            PO_EDIT_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_save_value),
                CallbackQueryHandler(edit_save_confirm),
                CallbackQueryHandler(edit_payout_start, pattern="^edit_payout$"),
                CallbackQueryHandler(payout_back, pattern="^payout_menu$")
            ],
        },
        fallbacks=[CommandHandler("cancel", payout_back)],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(edit_conv)

    # ----------- Delete payout -------------
    del_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_payout_start, pattern="^remove_payout$")],
        states={
            PO_DEL_PARTNER: [CallbackQueryHandler(del_choose_period,  pattern="^po_del_part_\\d+$"),
                             CallbackQueryHandler(payout_back, pattern="^payout_menu$")],
            PO_DEL_TIME:    [CallbackQueryHandler(del_set_filter,     pattern="^po_del_filt_"),
                             CallbackQueryHandler(remove_payout_start,   pattern="^remove_payout$"),
                             CallbackQueryHandler(payout_back,        pattern="^payout_menu$")],
            PO_DEL_PAGE: [
                CallbackQueryHandler(del_paginate, pattern="^po_del_(prev|next)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, del_pick_doc),
                CallbackQueryHandler(remove_payout_start,   pattern="^remove_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$")
            ],
            PO_DEL_CONFIRM: [
                CallbackQueryHandler(confirm_delete_payout),
                CallbackQueryHandler(remove_payout_start,   pattern="^remove_payout$"),
                CallbackQueryHandler(payout_back,        pattern="^payout_menu$")
            ],
        },
        fallbacks=[CommandHandler("cancel", payout_back)],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(del_conv)
