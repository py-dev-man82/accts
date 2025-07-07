# handlers/payments.py
"""Payments module – revamped to mirror stockin/sales-style flows.
Add / View / Edit / Remove payments with customer picker, period filter, pagination,
consistent back-navigation buttons, and robust conversation handlers.
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

from handlers.utils import require_unlock
from secure_db import secure_db

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────
#  Conversation-state constants
# ───────────────────────────────────────────────────────────────
(
    P_ADD_CUST,   P_ADD_LOCAL,  P_ADD_FEE,    P_ADD_USD,    P_ADD_NOTE,  P_ADD_DATE,  P_ADD_CONFIRM,
    P_VIEW_CUST,  P_VIEW_TIME,  P_VIEW_PAGE,
    P_EDIT_CUST,  P_EDIT_TIME,  P_EDIT_PAGE,  P_EDIT_LOCAL, P_EDIT_FEE,  P_EDIT_USD, P_EDIT_DATE, P_EDIT_CONFIRM,
    P_DEL_CUST,   P_DEL_TIME,   P_DEL_PAGE,   P_DEL_CONFIRM,
) = range(22)

ROWS_PER_PAGE = 20   # keep UI consistent with sales & stock-in

# ───────────────────────────────────────────────────────────────
#  Helper – months filter
# ───────────────────────────────────────────────────────────────
def _months_filter(rows, months: int):
    """Return rows with date >= first day of (current month − months)."""
    if months <= 0:
        return rows
    cutoff = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    m = cutoff.month - months
    y = cutoff.year
    if m <= 0:
        m += 12
        y -= 1
    cutoff = cutoff.replace(year=y, month=m)
    return [
        r
        for r in rows
        if datetime.strptime(r.get("date", "01011970"), "%d%m%Y") >= cutoff
    ]

# ───────────────────────────────────────────────────────────────
#  Sub-menu (called from main menu & after flows)
# ───────────────────────────────────────────────────────────────
async def show_payment_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # answer any callback to remove the spinner
    if update.callback_query:
        await update.callback_query.answer()
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Add Payment",    callback_data="add_payment")],
            [InlineKeyboardButton("👀 View Payments",  callback_data="view_payment")],
            [InlineKeyboardButton("✏️ Edit Payment",   callback_data="edit_payment")],
            [InlineKeyboardButton("🗑️ Remove Payment", callback_data="remove_payment")],
            [InlineKeyboardButton("🔙 Back",           callback_data="main_menu")],
        ]
    )
    if update.callback_query:
        await update.callback_query.edit_message_text("💰 Payments: choose an action", reply_markup=kb)
    else:
        await update.message.reply_text("💰 Payments: choose an action", reply_markup=kb)

# ======================================================================
#                              ADD  FLOW
# ======================================================================
@require_unlock
async def add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = secure_db.all("customers")
    if not rows:
        await update.callback_query.edit_message_text(
            "⚠️ No customers configured.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]),
        )
        return ConversationHandler.END
    buttons = [
        InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"pay_add_cust_{r.doc_id}")
        for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i : i + 2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return P_ADD_CUST


async def get_add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["customer_id"] = int(update.callback_query.data.split("_")[-1])
    await update.callback_query.edit_message_text("Enter amount received (local currency):")
    return P_ADD_LOCAL


async def get_add_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text)
        assert amt > 0
    except Exception:
        await update.message.reply_text("❌ Positive number, please.")
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="pay_add_note_skip")]])
    await update.message.reply_text("Enter an optional note or Skip:", reply_markup=kb)
    return P_ADD_NOTE


async def get_add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = "" if (update.callback_query and update.callback_query.data.endswith("skip")) else update.message.text.strip()
    if update.callback_query:
        await update.callback_query.answer()
    context.user_data["note"] = note
    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="pay_add_date_skip")]])
    prompt = f"Enter payment date DDMMYYYY or Skip ({today}):"
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


async def confirm_add_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    fee_amt = d["local_amt"] * d["fee_perc"] / 100
    net = d["local_amt"] - fee_amt
    fx = (net / d["usd_amt"]) if d["usd_amt"] else 0
    summary = (
        f"Local: {d['local_amt']:.2f}\n"
        f"Fee: {d['fee_perc']:.2f}% ({fee_amt:.2f})\n"
        f"USD Recv: {d['usd_amt']:.2f}\n"
        f"FX Rate: {fx:.4f}\n"
        f"Note: {d.get('note') or '—'}\n"
        f"Date: {d['date']}"
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirm", callback_data="pay_add_conf_yes"),
             InlineKeyboardButton("❌ Cancel",  callback_data="pay_add_conf_no")],
        ]
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_ADD_CONFIRM


@require_unlock
async def confirm_add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("no"):
        await show_payment_menu(update, context)
        return ConversationHandler.END
    d = context.user_data
    rec_id = secure_db.insert(
        "customer_payments",
        {
            "customer_id": d["customer_id"],
            "local_amt": d["local_amt"],
            "fee_perc": d["fee_perc"],
            "usd_amt": d["usd_amt"],
            "note": d.get("note", ""),
            "date": d["date"],
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    await update.callback_query.edit_message_text(
        f"✅ Payment recorded (ID {rec_id}).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]),
    )
    return ConversationHandler.END

# ======================================================================
#                       VIEW  FLOW  (Customer → Period → Pages)
# ======================================================================
@require_unlock
async def view_payment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1 of View flow – choose customer."""
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]),
        )
        return ConversationHandler.END
    buttons = [
        InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"pay_view_cust_{c.doc_id}")
        for c in customers
    ]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="payment_menu"))
    kb = InlineKeyboardMarkup([buttons[i : i + 2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return P_VIEW_CUST


async def view_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_cid"] = int(update.callback_query.data.split("_")[-1])
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📆 Last 3 M", callback_data="pay_view_filt_3m")],
            [InlineKeyboardButton("📆 Last 6 M", callback_data="pay_view_filt_6m")],
            [InlineKeyboardButton("🗓️ All",      callback_data="pay_view_filt_all")],
            [InlineKeyboardButton("🔙 Back",     callback_data="view_payment")],
        ]
    )
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return P_VIEW_TIME


async def view_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_period"] = update.callback_query.data.split("_")[-1]  # 3m / 6m / all
    context.user_data["view_page"] = 1
    return await render_view_page(update, context)


async def render_view_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = context.user_data["view_cid"]
    period = context.user_data["view_period"]
    page = context.user_data["view_page"]

    rows = [r for r in secure_db.all("customer_payments") if r["customer_id"] == cid]
    if period != "all":
        rows = _months_filter(rows, int(period.rstrip("m")))
    rows.sort(key=lambda r: datetime.strptime(r.get("date", "01011970"), "%d%m%Y"), reverse=True)

    total = len(rows)
    start, end = (page - 1) * ROWS_PER_PAGE, page * ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No payments for that period."
    else:
        lines = []
        for r in chunk:
            fee_amt = r["local_amt"] * r["fee_perc"] / 100
            net = r["local_amt"] - fee_amt
            fx = (net / r["usd_amt"]) if r["usd_amt"] else 0
            lines.append(f"[{r.doc_id}] {r['local_amt']:.2f} ➜ {r['usd_amt']:.2f} USD on {r['date']} | FX {fx:.4f}")
        text = f"💰 Payments P{page} / {(total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE}\n\n" + "\n".join(lines)

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="pay_view_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="pay_view_next"))
    kb = InlineKeyboardMarkup([nav, [InlineKeyboardButton("🔙 Back", callback_data="view_payment")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return P_VIEW_PAGE


async def view_paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("prev"):
        context.user_data["view_page"] -= 1
    else:
        context.user_data["view_page"] += 1
    return await render_view_page(update, context)

# ======================================================================
#                       EDIT  FLOW  (Customer → Period → Pages)
# ======================================================================
@require_unlock
async def edit_payment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1 of Edit flow – choose customer."""
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]),
        )
        return ConversationHandler.END
    buttons = [
        InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"pay_edit_cust_{c.doc_id}")
        for c in customers
    ]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="payment_menu"))
    kb = InlineKeyboardMarkup([buttons[i : i + 2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return P_EDIT_CUST


async def edit_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_cid"] = int(update.callback_query.data.split("_")[-1])
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📆 Last 3 M", callback_data="pay_edit_filt_3m")],
            [InlineKeyboardButton("📆 Last 6 M", callback_data="pay_edit_filt_6m")],
            [InlineKeyboardButton("🗓️ All",      callback_data="pay_edit_filt_all")],
            [InlineKeyboardButton("🔙 Back",     callback_data="edit_payment")],
        ]
    )
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return P_EDIT_TIME


async def edit_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_period"] = update.callback_query.data.split("_")[-1]
    context.user_data["edit_page"] = 1
    return await render_edit_page(update, context)


async def render_edit_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = context.user_data["edit_cid"]
    period = context.user_data["edit_period"]
    page = context.user_data["edit_page"]

    rows = [r for r in secure_db.all("customer_payments") if r["customer_id"] == cid]
    if period != "all":
        rows = _months_filter(rows, int(period.rstrip("m")))
    rows.sort(key=lambda r: datetime.strptime(r.get("date", "01011970"), "%d%m%Y"), reverse=True)

    total = len(rows)
    start, end = (page - 1) * ROWS_PER_PAGE, page * ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No payments."
    else:
        lines = [f"[{r.doc_id}] {r['local_amt']:.2f} ➜ {r['usd_amt']:.2f} USD" for r in chunk]
        text = f"✏️ Edit Payments P{page}/{(total + ROWS_PER_PAGE - 1)//ROWS_PER_PAGE}\n\n" + "\n".join(lines)
        text += "\n\nSend DocID to edit:"

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="pay_edit_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="pay_edit_next"))
    kb = InlineKeyboardMarkup([nav, [InlineKeyboardButton("🔙 Back", callback_data="edit_payment")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return P_EDIT_PAGE


async def edit_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_page"] += -1 if update.callback_query.data.endswith("prev") else 1
    return await render_edit_page(update, context)


async def edit_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pid = int(update.message.text.strip())
        rec = secure_db.table("customer_payments").get(doc_id=pid)
        assert rec and rec["customer_id"] == context.user_data["edit_cid"]
    except Exception:
        await update.message.reply_text("❌ Invalid ID; try again:")
        return P_EDIT_PAGE
    context.user_data["edit_rec"] = rec
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip", callback_data="pay_edit_date_skip")]])
    await update.message.reply_text(f"New date DDMMYYYY or Skip ({today}):", reply_markup=kb)
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
    d = context.user_data
    summary = (
        f"Local: {d['new_local']:.2f}\n"
        f"Fee: {d['new_fee']:.2f}%\n"
        f"USD: {d['new_usd']:.2f}\n"
        f"Date: {date_str}\n\n"
        f"Save?"
    )
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Save", callback_data="pay_edit_conf_yes"),
          InlineKeyboardButton("❌ Cancel", callback_data="pay_edit_conf_no")]]
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_EDIT_CONFIRM


@require_unlock
async def edit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("_no"):
        await show_payment_menu(update, context)
        return ConversationHandler.END
    rec = context.user_data["edit_rec"]
    secure_db.update(
        "customer_payments",
        {
            "local_amt": context.user_data["new_local"],
            "fee_perc": context.user_data["new_fee"],
            "usd_amt": context.user_data["new_usd"],
            "date": context.user_data["new_date"],
        },
        [rec.doc_id],
    )
    await update.callback_query.edit_message_text(
        "✅ Payment updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]),
    )
    return ConversationHandler.END

# ======================================================================
#                       DELETE  FLOW  (Customer → Period → Pages)
# ======================================================================
@require_unlock
async def del_payment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1 of Delete flow – choose customer."""
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]),
        )
        return ConversationHandler.END
    buttons = [
        InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"pay_del_cust_{c.doc_id}")
        for c in customers
    ]
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="payment_menu"))
    kb = InlineKeyboardMarkup([buttons[i : i + 2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return P_DEL_CUST


async def del_choose_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_cid"] = int(update.callback_query.data.split("_")[-1])
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📆 Last 3 M", callback_data="pay_del_filt_3m")],
            [InlineKeyboardButton("📆 Last 6 M", callback_data="pay_del_filt_6m")],
            [InlineKeyboardButton("🗓️ All",      callback_data="pay_del_filt_all")],
            [InlineKeyboardButton("🔙 Back",     callback_data="remove_payment")],
        ]
    )
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return P_DEL_TIME


async def del_set_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_period"] = update.callback_query.data.split("_")[-1]
    context.user_data["del_page"] = 1
    return await render_del_page(update, context)


async def render_del_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = context.user_data["del_cid"]
    period = context.user_data["del_period"]
    page = context.user_data["del_page"]

    rows = [r for r in secure_db.all("customer_payments") if r["customer_id"] == cid]
    if period != "all":
        rows = _months_filter(rows, int(period.rstrip("m")))
    rows.sort(key=lambda r: datetime.strptime(r.get("date", "01011970"), "%d%m%Y"), reverse=True)

    total = len(rows)
    start, end = (page - 1) * ROWS_PER_PAGE, page * ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No payments."
    else:
        lines = [f"[{r.doc_id}] {r['local_amt']:.2f} ➜ {r['usd_amt']:.2f} USD" for r in chunk]
        text = f"🗑️ Delete Payments P{page}/{(total + ROWS_PER_PAGE - 1)//ROWS_PER_PAGE}\n\n" + "\n".join(lines)
        text += "\n\nSend DocID to delete:"

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="pay_del_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="pay_del_next"))
    kb = InlineKeyboardMarkup([nav, [InlineKeyboardButton("🔙 Back", callback_data="remove_payment")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return P_DEL_PAGE


async def del_page_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_page"] += -1 if update.callback_query.data.endswith("prev") else 1
    return await render_del_page(update, context)


async def del_pick_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pid = int(update.message.text.strip())
        rec = secure_db.table("customer_payments").get(doc_id=pid)
        assert rec and rec["customer_id"] == context.user_data["del_cid"]
    except Exception:
        await update.message.reply_text("❌ Invalid ID; try again:")
        return P_DEL_PAGE
    context.user_data["del_rec"] = rec
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Yes", callback_data="pay_del_conf_yes"),
          InlineKeyboardButton("❌ No",  callback_data="pay_del_conf_no")]]
    )
    await update.message.reply_text(f"Delete Payment [{pid}]?", reply_markup=kb)
    return P_DEL_CONFIRM


@require_unlock
async def del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data.endswith("_no"):
        await show_payment_menu(update, context)
        return ConversationHandler.END
    rec = context.user_data["del_rec"]
    secure_db.remove("customer_payments", [rec.doc_id])
    await update.callback_query.edit_message_text(
        "✅ Payment deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]),
    )
    return ConversationHandler.END

# ======================================================================
#                   REGISTER ALL HANDLERS FOR MODULE
# ======================================================================
def register_payment_handlers(app: Application):
    """Attach Payments submenu + all conversations to the Telegram app."""

    # ── Sub-menu (always present)
    app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))

    # ───────────────────────── Add conversation ─────────────────────────
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_payment, pattern="^add_payment$")],
        states={
            P_ADD_CUST: [
                CallbackQueryHandler(get_add_customer, pattern="^pay_add_cust_\\d+$"),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
            P_ADD_LOCAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_local),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
            P_ADD_FEE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_fee),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
            P_ADD_USD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_usd),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
            P_ADD_NOTE: [
                CallbackQueryHandler(get_add_note, pattern="^pay_add_note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_note),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
            P_ADD_DATE: [
                CallbackQueryHandler(get_add_date, pattern="^pay_add_date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_add_date),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
            P_ADD_CONFIRM: [
                CallbackQueryHandler(confirm_add_payment, pattern="^pay_add_conf_(yes|no)$"),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", show_payment_menu)],
        per_message=False,
    )
    app.add_handler(add_conv)

    # ───────────────────────── View conversation ─────────────────────────
    view_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(view_payment_start, pattern="^view_payment$")],
        states={
            P_VIEW_CUST: [
                CallbackQueryHandler(view_choose_period, pattern="^pay_view_cust_\\d+$"),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
            P_VIEW_TIME: [
                CallbackQueryHandler(view_set_filter, pattern="^pay_view_filt_"),
                CallbackQueryHandler(view_payment_start, pattern="^view_payment$"),
            ],
            P_VIEW_PAGE: [
                CallbackQueryHandler(view_paginate, pattern="^pay_view_(prev|next)$"),
                CallbackQueryHandler(view_payment_start, pattern="^view_payment$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", show_payment_menu)],
        per_message=False,
    )
    app.add_handler(view_conv)

    # ───────────────────────── Edit conversation ─────────────────────────
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_payment_start, pattern="^edit_payment$")],
        states={
            P_EDIT_CUST: [
                CallbackQueryHandler(edit_choose_period, pattern="^pay_edit_cust_\\d+$"),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
            P_EDIT_TIME: [
                CallbackQueryHandler(edit_set_filter, pattern="^pay_edit_filt_"),
                CallbackQueryHandler(edit_payment_start, pattern="^edit_payment$"),
            ],
            P_EDIT_PAGE: [
                CallbackQueryHandler(edit_page_nav, pattern="^pay_edit_(prev|next)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_pick_doc),
                CallbackQueryHandler(edit_payment_start, pattern="^edit_payment$"),
            ],
            P_EDIT_LOCAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_local),
                CallbackQueryHandler(edit_payment_start, pattern="^edit_payment$"),
            ],
            P_EDIT_FEE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_fee),
                CallbackQueryHandler(edit_payment_start, pattern="^edit_payment$"),
            ],
            P_EDIT_USD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_usd),
                CallbackQueryHandler(edit_payment_start, pattern="^edit_payment$"),
            ],
            P_EDIT_DATE: [
                CallbackQueryHandler(edit_new_date, pattern="^pay_edit_date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_date),
                CallbackQueryHandler(edit_payment_start, pattern="^edit_payment$"),
            ],
            P_EDIT_CONFIRM: [
                CallbackQueryHandler(edit_save, pattern="^pay_edit_conf_(yes|no)$"),
                CallbackQueryHandler(edit_payment_start, pattern="^edit_payment$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", show_payment_menu)],
        per_message=False,
    )
    app.add_handler(edit_conv)

    # ───────────────────────── Delete conversation ────────────────────────
    del_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(del_payment_start, pattern="^remove_payment$")],
        states={
            P_DEL_CUST: [
                CallbackQueryHandler(del_choose_period, pattern="^pay_del_cust_\\d+$"),
                CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"),
            ],
            P_DEL_TIME: [
                CallbackQueryHandler(del_set_filter, pattern="^pay_del_filt_"),
                CallbackQueryHandler(del_payment_start, pattern="^remove_payment$"),
            ],
            P_DEL_PAGE: [
                CallbackQueryHandler(del_page_nav, pattern="^pay_del_(prev|next)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, del_pick_doc),
                CallbackQueryHandler(del_payment_start, pattern="^remove_payment$"),
            ],
            P_DEL_CONFIRM: [
                CallbackQueryHandler(del_confirm, pattern="^pay_del_conf_(yes|no)$"),
                CallbackQueryHandler(del_payment_start, pattern="^remove_payment$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", show_payment_menu)],
        per_message=False,
    )
    app.add_handler(del_conv)
