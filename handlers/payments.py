# ======================================================================
#   PAYMENTS MODULE – LEDGER-LINKED, RELATED-ID, AND UI CONSISTENT 
# ======================================================================

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

from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import add_ledger_entry, delete_ledger_entries_by_related
from secure_db import secure_db
from tinydb import Query

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────
#  Conversation-state constants
# ───────────────────────────────────────────────────────────────
(
    P_ADD_CUST,   P_ADD_LOCAL,  P_ADD_FEE,   P_ADD_USD,
    P_ADD_NOTE,   P_ADD_DATE,   P_ADD_CONFIRM,

    P_VIEW_CUST,  P_VIEW_TIME,  P_VIEW_PAGE,

    P_EDIT_CUST,  P_EDIT_TIME,  P_EDIT_PAGE,
    P_EDIT_LOCAL, P_EDIT_FEE,   P_EDIT_USD,
    P_EDIT_DATE,  P_EDIT_CONFIRM,

    P_DEL_CUST,   P_DEL_TIME,   P_DEL_PAGE,  P_DEL_CONFIRM,
) = range(22)

ROWS_PER_PAGE = 20

# ───────────────────────────────────────────────────────────────
#  Helpers / Formatters
# ───────────────────────────────────────────────────────────────

def _short_date(dstr):
    """DDMMYYYY -> DD/MM/YY"""
    try:
        dt = datetime.strptime(dstr, "%d%m%Y")
        return dt.strftime("%d/%m/%y")
    except Exception:
        return dstr

def _cust_currency(cid: int) -> str:
    row = secure_db.table("customers").get(doc_id=cid) or {}
    return row.get("currency", "USD")

def _months_filter(rows, months: int):
    if months <= 0:
        return rows
    cutoff = datetime.utcnow().replace(day=1, hour=0, minute=0,
                                       second=0, microsecond=0)
    m = cutoff.month - months
    y = cutoff.year
    if m <= 0:
        m += 12
        y -= 1
    cutoff = cutoff.replace(year=y, month=m)
    return [
        r for r in rows
        if datetime.strptime(r.get("date", "01011970"), "%d%m%Y") >= cutoff
    ]

def _format_payment_row(r, currency):
    rid = r.get("related_id", r.doc_id)
    shortd = _short_date(r.get("date", ""))
    fee_amt = r["local_amt"] * r.get("fee_perc", 0) / 100
    net = r["local_amt"] - fee_amt
    fx = (net / r["usd_amt"]) if r.get("usd_amt") else 0
    return (f"{rid}: {shortd}: {fmt_money(r['local_amt'], currency)} ➜ "
            f"{fmt_money(r['usd_amt'], 'USD')} | FX {fx:.4f}")


# ───────────────────────────────────────────────────────────────
#  Sub-menu & universal Back handler
# ───────────────────────────────────────────────────────────────

async def show_payment_menu(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Payment",    callback_data="add_payment")],
        [InlineKeyboardButton("👀 View Payments",  callback_data="view_payment")],
        [InlineKeyboardButton("✏️ Edit Payment",   callback_data="edit_payment")],
        [InlineKeyboardButton("🗑️ Remove Payment", callback_data="remove_payment")],
        [InlineKeyboardButton("🔙 Back",           callback_data="main_menu")],
    ])
    msg = "💰 Payments: choose an action"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def payment_back(update: Update,
                       context: ContextTypes.DEFAULT_TYPE):
    """Abort any conversation, clear temp data, return to Payments menu."""
    context.user_data.clear()
    await show_payment_menu(update, context)
    return ConversationHandler.END

# ======================================================================
#                               ADD FLOW
# ======================================================================

@require_unlock
async def add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "⚠️ No customers configured.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
            ),
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"pay_add_cust_{c.doc_id}")
               for c in customers]
    kb = InlineKeyboardMarkup([buttons[i:i+2]
                               for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:",
                                                  reply_markup=kb)
    return P_ADD_CUST

async def get_add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["customer_id"] = int(
        update.callback_query.data.split("_")[-1]
    )
    await update.callback_query.edit_message_text(
        "Enter amount received (local currency):"
    )
    return P_ADD_LOCAL

async def get_add_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text)
        assert amt > 0
    except Exception:
        await update.message.reply_text("❌ Positive number please.")
        return P_ADD_LOCAL
    context.user_data["local_amt"] = amt
    await update.message.reply_text("Enter handling fee % (0–99):")
    return P_ADD_FEE

async def get_add_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee = float(update.message.text)
        assert 0 <= fee < 100
    except Exception:
        await update.message.reply_text("❌ Percent 0–99 please.")
        return P_ADD_FEE
    context.user_data["fee_perc"] = fee
    await update.message.reply_text("Enter USD amount received:")
    return P_ADD_USD

async def get_add_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text)
        assert usd >= 0
    except Exception:
        await update.message.reply_text("❌ Number please.")
        return P_ADD_USD
    context.user_data["usd_amt"] = usd
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("➖ Skip note", callback_data="pay_add_note_skip")]]
    )
    await update.message.reply_text("Enter an optional note or Skip:",
                                    reply_markup=kb)
    return P_ADD_NOTE

async def get_add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = "" if (update.callback_query and
                  update.callback_query.data.endswith("skip")) \
                else update.message.text.strip()
    if update.callback_query:
        await update.callback_query.answer()
    context.user_data["note"] = note
    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📅 Skip date",
                               callback_data="pay_add_date_skip")]]
    )
    prompt = f"Enter payment date DDMMYYYY or Skip ({_short_date(today)}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return P_ADD_DATE

async def get_add_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date_str = datetime.now().strftime("%d%m%Y")
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, "%d%m%Y")
        except ValueError:
            await update.message.reply_text("❌ Format DDMMYYYY.")
            return P_ADD_DATE
    context.user_data["date"] = date_str
    return await confirm_add_prompt(update, context)

async def confirm_add_prompt(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    d   = context.user_data
    cur = _cust_currency(d["customer_id"])
    fee_amt = d["local_amt"] * d["fee_perc"] / 100
    net     = d["local_amt"] - fee_amt
    fx      = (net / d["usd_amt"]) if d["usd_amt"] else 0
    summary = (
        f"Local: {fmt_money(d['local_amt'], cur)}\n"
        f"Fee: {d['fee_perc']:.2f}% ({fmt_money(fee_amt, cur)})\n"
        f"USD Recv: {fmt_money(d['usd_amt'], 'USD')}\n"
        f"FX Rate: {fx:.4f}\n"
        f"Note: {d.get('note') or '—'}\n"
        f"Date: {_short_date(d['date'])}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="pay_add_conf_yes"),
         InlineKeyboardButton("❌ Cancel",  callback_data="pay_add_conf_no")]
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_ADD_CONFIRM

@require_unlock
async def confirm_add_payment(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("no"):
        return await payment_back(update, context)
    d = context.user_data

    # === Ledger-linked: write ledger first, save related_id ===
    cur = _cust_currency(d["customer_id"])
    fee_amt = d["local_amt"] * d["fee_perc"] / 100
    fx      = (d["local_amt"] - fee_amt) / d["usd_amt"] if d["usd_amt"] else 0
    payment_id = None

    try:
        # 1. Write ledger for customer (local currency, related_id=None)
        related_id = add_ledger_entry(
            account_type="customer",
            account_id=d["customer_id"],
            entry_type="payment",
            related_id=None,
            amount=d["local_amt"],
            currency=cur,
            note=d.get('note', ''),
            date=d["date"],
            fee_perc=d["fee_perc"],
            fee_amt=fee_amt,
            fx_rate=fx,
            usd_amt=d["usd_amt"]
        )
        # 2. Write ledger for owner (USD/POT, same related_id)
        add_ledger_entry(
            account_type="owner",
            account_id="POT",
            entry_type="payment_recv",
            related_id=related_id,
            amount=d["usd_amt"],
            currency="USD",
            note=d.get('note', ''),
            date=d["date"],
            fee_perc=d["fee_perc"],
            fee_amt=fee_amt,
            fx_rate=fx,
            usd_amt=d["usd_amt"]
        )
        # 3. Insert payment record with related_id
        payment_id = secure_db.insert("customer_payments", {
            "customer_id": d["customer_id"],
            "local_amt":   d["local_amt"],
            "fee_perc":    d["fee_perc"],
            "usd_amt":     d["usd_amt"],
            "note":        d["note"],
            "date":        d["date"],
            "timestamp":   datetime.utcnow().isoformat(),
            "related_id":  related_id
        })
    except Exception as e:
        logger.error(f"Ledger failed for payment: {e}")
        if payment_id:
            secure_db.remove("customer_payments", [payment_id])
        await update.callback_query.edit_message_text(
            "❌ Error: Failed to write to ledger. Payment not recorded.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
            ),
        )
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        "✅ Payment recorded (ledger updated).",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
        ),
    )
    return ConversationHandler.END

# ======================================================================
#                       VIEW FLOW  (Customer → Period → Pages)
# ======================================================================

def _short_date(date_str):
    # Convert DDMMYYYY to DD/MM/YY for compact display
    try:
        dt = datetime.strptime(date_str, "%d%m%Y")
        return dt.strftime("%d/%m/%y")
    except Exception:
        return date_str

@require_unlock
async def view_payment_start(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
            ),
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"pay_view_cust_{c.doc_id}")
               for c in customers]
    buttons.append(InlineKeyboardButton("🔙 Back",
                                        callback_data="payment_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2]
                               for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:",
                                                  reply_markup=kb)
    return P_VIEW_CUST

async def view_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_cid"] = int(
        update.callback_query.data.split("_")[-1]
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M", callback_data="pay_view_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M", callback_data="pay_view_filt_6m")],
        [InlineKeyboardButton("🗓️ All",      callback_data="pay_view_filt_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="view_payment")],
    ])
    await update.callback_query.edit_message_text("Choose period:",
                                                  reply_markup=kb)
    return P_VIEW_TIME

async def view_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_period"] = update.callback_query.data.split("_")[-1]
    context.user_data["view_page"]   = 1
    return await render_view_page(update, context)

async def render_view_page(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    cid    = context.user_data["view_cid"]
    period = context.user_data["view_period"]
    page   = context.user_data["view_page"]
    cur    = _cust_currency(cid)

    rows = [r for r in secure_db.all("customer_payments")
            if r["customer_id"] == cid]
    if period != "all":
        rows = _months_filter(rows, int(period.rstrip("m")))
    rows.sort(key=lambda r:
              datetime.strptime(r.get("date", "01011970"), "%d%m%Y"),
              reverse=True)

    total = len(rows)
    start, end = (page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No payments for that period."
    else:
        lines = []
        for r in chunk:
            fee_amt = r["local_amt"] * r["fee_perc"] / 100
            net     = r["local_amt"] - fee_amt
            fx      = (net / r["usd_amt"]) if r["usd_amt"] else 0
            # Use related_id if present, else doc_id for legacy
            ref_id = r.get("related_id", r.doc_id)
            text_line = (
                f"{ref_id}: {_short_date(r['date'])}: {fmt_money(r['local_amt'], cur)} ➜ "
                f"{fmt_money(r['usd_amt'], 'USD')} | FX {fx:.4f}"
            )
            lines.append(text_line)
        text = (f"💰 Payments  P{page}/"
                f"{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
                + "\n".join(lines)
                + "\n\nReply with reference number or use arrows.")

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="pay_view_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="pay_view_next"))
    kb = InlineKeyboardMarkup([nav,
                               [InlineKeyboardButton("🔙 Back",
                                                     callback_data="view_payment")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return P_VIEW_PAGE

async def view_paginate(update: Update,
                        context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_page"] += \
        (-1 if update.callback_query.data.endswith("prev") else 1)
    return await render_view_page(update, context)

# ======================================================================
#                       EDIT FLOW  (Customer → Period → Pages)
# ======================================================================

@require_unlock
async def edit_payment_start(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
            ),
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"pay_edit_cust_{c.doc_id}")
               for c in customers]
    buttons.append(InlineKeyboardButton("🔙 Back",
                                        callback_data="payment_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2]
                               for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:",
                                                  reply_markup=kb)
    return P_EDIT_CUST

async def edit_choose_period(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_cid"] = int(
        update.callback_query.data.split("_")[-1]
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M", callback_data="pay_edit_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M", callback_data="pay_edit_filt_6m")],
        [InlineKeyboardButton("🗓️ All",      callback_data="pay_edit_filt_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="edit_payment")],
    ])
    await update.callback_query.edit_message_text("Choose period:",
                                                  reply_markup=kb)
    return P_EDIT_TIME

async def edit_set_filter(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_period"] = update.callback_query.data.split("_")[-1]
    context.user_data["edit_page"]   = 1
    return await render_edit_page(update, context)

async def render_edit_page(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    cid    = context.user_data["edit_cid"]
    period = context.user_data["edit_period"]
    page   = context.user_data["edit_page"]
    cur    = _cust_currency(cid)

    rows = [r for r in secure_db.all("customer_payments")
            if r["customer_id"] == cid]
    if period != "all":
        rows = _months_filter(rows, int(period.rstrip("m")))
    rows.sort(key=lambda r:
              datetime.strptime(r.get("date", "01011970"), "%d%m%Y"),
              reverse=True)

    total = len(rows)
    start, end = (page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No payments."
    else:
        lines = []
        for r in chunk:
            ref_id = r.get("related_id", r.doc_id)
            text_line = (
                f"{ref_id}: {_short_date(r['date'])}: {fmt_money(r['local_amt'], cur)} ➜ "
                f"{fmt_money(r['usd_amt'],'USD')}"
            )
            lines.append(text_line)
        text = (f"✏️ Edit Payments  P{page}/"
                f"{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
                + "\n".join(lines)
                + "\n\nReply with reference number to edit or use arrows.")

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="pay_edit_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="pay_edit_next"))
    kb = InlineKeyboardMarkup([nav,
                               [InlineKeyboardButton("🔙 Back",
                                                     callback_data="edit_payment")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return P_EDIT_PAGE

async def edit_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_page"] += \
        (-1 if update.callback_query.data.endswith("prev") else 1)
    return await render_edit_page(update, context)

async def edit_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rid = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌ Enter numeric reference number.")
        return P_EDIT_PAGE
    # Search using related_id, fallback to doc_id for legacy
    q = Query()
    rec = secure_db.table("customer_payments").get((q.related_id == rid) | (q.doc_id == rid))
    if not rec or rec["customer_id"] != context.user_data["edit_cid"]:
        await update.message.reply_text("❌ ID not in current list.")
        return P_EDIT_PAGE
    context.user_data["edit_rec"] = rec
    context.user_data["edit_rid"] = rec.get("related_id", rec.doc_id)
    await update.message.reply_text("New local amount:")
    return P_EDIT_LOCAL

async def edit_new_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text)
        assert amt > 0
    except Exception:
        await update.message.reply_text("Positive number:")
        return P_EDIT_LOCAL
    context.user_data["new_local"] = amt
    await update.message.reply_text("New fee %:")
    return P_EDIT_FEE

async def edit_new_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee = float(update.message.text)
        assert 0 <= fee < 100
    except Exception:
        await update.message.reply_text("0–99 please.")
        return P_EDIT_FEE
    context.user_data["new_fee"] = fee
    await update.message.reply_text("New USD amount:")
    return P_EDIT_USD

async def edit_new_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text)
        assert usd >= 0
    except Exception:
        await update.message.reply_text("Number please.")
        return P_EDIT_USD
    context.user_data["new_usd"] = usd
    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📅 Skip",
                               callback_data="pay_edit_date_skip")]]
    )
    await update.message.reply_text(f"New date DDMMYYYY or Skip ({_short_date(today)}):",
                                    reply_markup=kb)
    return P_EDIT_DATE

async def edit_new_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        date_str = datetime.now().strftime("%d%m%Y")
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, "%d%m%Y")
        except ValueError:
            await update.message.reply_text("Format DDMMYYYY.")
            return P_EDIT_DATE
    context.user_data["new_date"] = date_str
    d   = context.user_data
    cur = _cust_currency(context.user_data["edit_cid"])
    summary = (
        f"Local: {fmt_money(d['new_local'], cur)}\n"
        f"Fee: {d['new_fee']:.2f}%\n"
        f"USD: {fmt_money(d['new_usd'],'USD')}\n"
        f"Date: {_short_date(date_str)}\n\nSave?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Save", callback_data="pay_edit_conf_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="pay_edit_conf_no")]
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_EDIT_CONFIRM

@require_unlock
async def edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("_no"):
        return await payment_back(update, context)

    rec = context.user_data["edit_rec"]
    cid = rec["customer_id"]
    rid = context.user_data["edit_rid"]
    cur = _cust_currency(cid)
    d = context.user_data

    # Save new values to DB (using doc_id)
    secure_db.update("customer_payments", {
        "local_amt": d["new_local"],
        "fee_perc":  d["new_fee"],
        "usd_amt":   d["new_usd"],
        "date":      d["new_date"],
    }, [rec.doc_id])

    try:
        # Remove ledger entries by related_id
        delete_ledger_entries_by_related("customer", cid, rid)
        delete_ledger_entries_by_related("owner", "POT", rid)

        fee_amt = d["new_local"] * d["new_fee"] / 100
        fx      = (d["new_local"] - fee_amt) / d["new_usd"] if d["new_usd"] else 0

        # Re-add ledger with updated values (using related_id for linkage)
        add_ledger_entry(
            account_type="customer",
            account_id=cid,
            entry_type="payment",
            related_id=rid,
            amount=d["new_local"],
            currency=cur,
            note=rec.get("note", ""),
            date=d["new_date"],
            fee_perc=d["new_fee"],
            fee_amt=fee_amt,
            fx_rate=fx,
            usd_amt=d["new_usd"]
        )
        add_ledger_entry(
            account_type="owner",
            account_id="POT",
            entry_type="payment_recv",
            related_id=rid,
            amount=d["new_usd"],
            currency="USD",
            note=rec.get("note", ""),
            date=d["new_date"],
            fee_perc=d["new_fee"],
            fee_amt=fee_amt,
            fx_rate=fx,
            usd_amt=d["new_usd"]
        )
    except Exception as e:
        logger.error(f"Ledger update failed for payment {rid}: {e}")
        await update.callback_query.edit_message_text(
            "❌ Error: Failed to update ledger. Payment not edited.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
            ),
        )
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        "✅ Payment updated (ledger synced).",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
        ),
    )
    return ConversationHandler.END

# ======================================================================
#                       DELETE FLOW  (Customer → Period → Pages)
# ======================================================================

@require_unlock
async def del_payment_start(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
            ),
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"pay_del_cust_{c.doc_id}")
               for c in customers]
    buttons.append(InlineKeyboardButton("🔙 Back",
                                        callback_data="payment_menu"))
    kb = InlineKeyboardMarkup([buttons[i:i+2]
                               for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:",
                                                  reply_markup=kb)
    return P_DEL_CUST

async def del_choose_period(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_cid"] = int(
        update.callback_query.data.split("_")[-1]
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📆 Last 3 M", callback_data="pay_del_filt_3m")],
        [InlineKeyboardButton("📆 Last 6 M", callback_data="pay_del_filt_6m")],
        [InlineKeyboardButton("🗓️ All",      callback_data="pay_del_filt_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="remove_payment")],
    ])
    await update.callback_query.edit_message_text("Choose period:",
                                                  reply_markup=kb)
    return P_DEL_TIME

async def del_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_period"] = update.callback_query.data.split("_")[-1]
    context.user_data["del_page"]   = 1
    return await render_del_page(update, context)

async def render_del_page(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    cid    = context.user_data["del_cid"]
    period = context.user_data["del_period"]
    page   = context.user_data["del_page"]
    cur    = _cust_currency(cid)

    rows = [r for r in secure_db.all("customer_payments")
            if r["customer_id"] == cid]
    if period != "all":
        rows = _months_filter(rows, int(period.rstrip("m")))
    rows.sort(key=lambda r:
              datetime.strptime(r.get("date", "01011970"), "%d%m%Y"),
              reverse=True)

    total = len(rows)
    start, end = (page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No payments."
    else:
        lines = []
        for r in chunk:
            ref_id = r.get("related_id", r.doc_id)
            text_line = (
                f"{ref_id}: {_short_date(r['date'])}: {fmt_money(r['local_amt'], cur)} ➜ "
                f"{fmt_money(r['usd_amt'],'USD')}"
            )
            lines.append(text_line)
        text = (f"🗑️ Delete Payments  P{page}/"
                f"{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
                + "\n".join(lines)
                + "\n\nReply with reference number to delete or use arrows.")

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="pay_del_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="pay_del_next"))
    kb = InlineKeyboardMarkup([nav,
                               [InlineKeyboardButton("🔙 Back",
                                                     callback_data="remove_payment")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return P_DEL_PAGE

async def del_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_page"] += \
        (-1 if update.callback_query.data.endswith("prev") else 1)
    return await render_del_page(update, context)

async def del_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rid = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌ Enter numeric reference number.")
        return P_DEL_PAGE
    # Search by related_id, fallback to doc_id for legacy
    q = Query()
    rec = secure_db.table("customer_payments").get((q.related_id == rid) | (q.doc_id == rid))
    if not rec or rec["customer_id"] != context.user_data["del_cid"]:
        await update.message.reply_text("❌ ID not in current list.")
        return P_DEL_PAGE
    context.user_data["del_rec"] = rec
    context.user_data["del_rid"] = rec.get("related_id", rec.doc_id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="pay_del_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="pay_del_conf_no")]
    ])
    await update.message.reply_text(f"Delete Payment {context.user_data['del_rid']}?",
                                    reply_markup=kb)
    return P_DEL_CONFIRM

@require_unlock
async def del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("_no"):
        return await payment_back(update, context)
    rec = context.user_data["del_rec"]
    cid = rec["customer_id"]
    rid = context.user_data["del_rid"]

    secure_db.remove("customer_payments", [rec.doc_id])
    try:
        delete_ledger_entries_by_related("customer", cid, rid)
        delete_ledger_entries_by_related("owner", "POT", rid)
    except Exception as e:
        logger.error(f"Ledger delete failed for payment {rid}: {e}")
        await update.callback_query.edit_message_text(
            "❌ Error: Failed to update ledger. Payment deleted in DB but not in ledger.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
            ),
        )
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        "✅ Payment deleted (ledger updated).",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]
        ),
    )
    return ConversationHandler.END


# ======================================================================
#                  REGISTER  ALL HANDLERS  FOR MODULE
# ======================================================================

def register_payment_handlers(app: Application):
    """Attach Payments submenu + all conversations to the Telegram app."""

    # ── Sub-menu
    app.add_handler(CallbackQueryHandler(show_payment_menu,
                                         pattern="^payment_menu$"))

    # ────────────────────── Add conversation ───────────────────────
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_payment,
                                           pattern="^add_payment$")],
        states={
            P_ADD_CUST: [
                CallbackQueryHandler(get_add_customer,
                                     pattern="^pay_add_cust_\\d+$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_ADD_LOCAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               get_add_local),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_ADD_FEE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               get_add_fee),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_ADD_USD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               get_add_usd),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_ADD_NOTE: [
                CallbackQueryHandler(get_add_note,
                                     pattern="^pay_add_note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               get_add_note),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_ADD_DATE: [
                CallbackQueryHandler(get_add_date,
                                     pattern="^pay_add_date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               get_add_date),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_ADD_CONFIRM: [
                CallbackQueryHandler(confirm_add_payment,
                                     pattern="^pay_add_conf_(yes|no)$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", payment_back)],
        per_message=False,
    )
    app.add_handler(add_conv)

    # ────────────────────── View conversation ───────────────────────
    view_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(view_payment_start,
                                           pattern="^view_payment$")],
        states={
            P_VIEW_CUST: [
                CallbackQueryHandler(view_choose_period,
                                     pattern="^pay_view_cust_\\d+$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_VIEW_TIME: [
                CallbackQueryHandler(view_set_filter,
                                     pattern="^pay_view_filt_"),
                CallbackQueryHandler(view_payment_start,
                                     pattern="^view_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_VIEW_PAGE: [
                CallbackQueryHandler(view_paginate,
                                     pattern="^pay_view_(prev|next)$"),
                CallbackQueryHandler(view_payment_start,
                                     pattern="^view_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", payment_back)],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(view_conv)

    # ────────────────────── Edit conversation ───────────────────────
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_payment_start,
                                           pattern="^edit_payment$")],
        states={
            P_EDIT_CUST: [
                CallbackQueryHandler(edit_choose_period,
                                     pattern="^pay_edit_cust_\\d+$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_EDIT_TIME: [
                CallbackQueryHandler(edit_set_filter,
                                     pattern="^pay_edit_filt_"),
                CallbackQueryHandler(edit_payment_start,
                                     pattern="^edit_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_EDIT_PAGE: [
                CallbackQueryHandler(edit_page_nav,
                                     pattern="^pay_edit_(prev|next)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               edit_pick_doc),
                CallbackQueryHandler(edit_payment_start,
                                     pattern="^edit_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_EDIT_LOCAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               edit_new_local),
                CallbackQueryHandler(edit_payment_start,
                                     pattern="^edit_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_EDIT_FEE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               edit_new_fee),
                CallbackQueryHandler(edit_payment_start,
                                     pattern="^edit_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_EDIT_USD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               edit_new_usd),
                CallbackQueryHandler(edit_payment_start,
                                     pattern="^edit_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_EDIT_DATE: [
                CallbackQueryHandler(edit_new_date,
                                     pattern="^pay_edit_date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               edit_new_date),
                CallbackQueryHandler(edit_payment_start,
                                     pattern="^edit_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_EDIT_CONFIRM: [
                CallbackQueryHandler(edit_save,
                                     pattern="^pay_edit_conf_(yes|no)$"),
                CallbackQueryHandler(edit_payment_start,
                                     pattern="^edit_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", payment_back)],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(edit_conv)

    # ────────────────────── Delete conversation ──────────────────────
    del_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(del_payment_start,
                                           pattern="^remove_payment$")],
        states={
            P_DEL_CUST: [
                CallbackQueryHandler(del_choose_period,
                                     pattern="^pay_del_cust_\\d+$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_DEL_TIME: [
                CallbackQueryHandler(del_set_filter,
                                     pattern="^pay_del_filt_"),
                CallbackQueryHandler(del_payment_start,
                                     pattern="^remove_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_DEL_PAGE: [
                CallbackQueryHandler(del_page_nav,
                                     pattern="^pay_del_(prev|next)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               del_pick_doc),
                CallbackQueryHandler(del_payment_start,
                                     pattern="^remove_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
            P_DEL_CONFIRM: [
                CallbackQueryHandler(del_confirm,
                                     pattern="^pay_del_conf_(yes|no)$"),
                CallbackQueryHandler(del_payment_start,
                                     pattern="^remove_payment$"),
                CallbackQueryHandler(payment_back, pattern="^payment_menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", payment_back)],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(del_conv)

# ---------------------- Utility: Short date formatter -----------------------

def _short_date(d: str) -> str:
    """Return DD/MM/YY from DDMMYYYY."""
    try:
        dt = datetime.strptime(d, "%d%m%Y")
        return dt.strftime("%d/%m/%y")
    except Exception:
        return d
