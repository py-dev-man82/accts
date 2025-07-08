# handlers/payments.py
"""
Payments module – modern UI (sales / stock-in pattern) **plus**
• Universal “Back” handling (like payouts.py)
• Friendly formatting helpers:
      fmt_money(…) → “$1 234 567.89”
      fmt_date(…)  → “15/06/2025”
• 🆕  Ledger integration on **add / edit / delete**  (see ledger.py)
• 🆕  Consistent logging (mirrors handlers/sales.py)
"""

from __future__ import annotations

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
from secure_db      import secure_db

# 🆕  Ledger helper (must exist in project root)
from ledger import add_ledger_entry    # add_ledger_entry(**kwargs)

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────
#  Conversation-state constants
# ───────────────────────────────────────────────────────────────
(
    P_CUST_SELECT,  P_LOCAL_AMT, P_FEE_PERC, P_USD_RECEIVED,
    P_NOTE,         P_DATE,      P_CONFIRM,

    P_VIEW_CUST,    P_VIEW_TIME, P_VIEW_PAGE,

    P_EDIT_CUST,    P_EDIT_TIME, P_EDIT_PAGE,
    P_EDIT_LOCAL,   P_EDIT_FEE,  P_EDIT_USD,
    P_EDIT_NOTE,    P_EDIT_DATE, P_EDIT_CONFIRM,

    P_DEL_CUST,     P_DEL_TIME,  P_DEL_PAGE,  P_DEL_CONFIRM,
) = range(23)

ROWS_PER_PAGE = 20


# ───────────────────────────────────────────────────────────────
#  Helpers
# ───────────────────────────────────────────────────────────────
def _months_filter(rows: list[dict], months: int) -> list[dict]:
    """Return rows dated within the last *months* full calendar months."""
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


def _cust_currency(cid: int) -> str:
    row = secure_db.table("customers").get(doc_id=cid) or {}
    return row.get("currency", "USD")


# ───────────────────────────────────────────────────────────────
#  Sub-menu  &  universal Back handler
# ───────────────────────────────────────────────────────────────
async def show_payment_menu(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Payment",    callback_data="add_payment")],
        [InlineKeyboardButton("👀 View Payments",  callback_data="view_payment")],
        [InlineKeyboardButton("✏️ Edit Payment",   callback_data="edit_payment")],
        [InlineKeyboardButton("🗑️ Remove Payment", callback_data="delete_payment")],
        [InlineKeyboardButton("🔙 Back",           callback_data="main_menu")],
    ])
    msg = "💰 Payments: choose an action"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)


async def payment_back(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> int:
    """Abort any conversation, clear temp data, return to Payments menu."""
    context.user_data.clear()
    await show_payment_menu(update, context)
    return ConversationHandler.END


# ╔══════════════════════════════════════════════════════════════╗
# ║                        ADD  FLOW                             ║
# ╚══════════════════════════════════════════════════════════════╝
@require_unlock
async def add_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Add payment – choose customer")
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "⚠️ No customers configured.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]),
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"pay_cust_{c.doc_id}")
               for c in customers]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return P_CUST_SELECT


async def get_payment_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data["customer_id"] = cid
    await update.callback_query.edit_message_text("Enter amount received (local currency):")
    return P_LOCAL_AMT


async def get_local_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text); assert amt > 0
    except Exception:
        await update.message.reply_text("❌ Positive number please.")
        return P_LOCAL_AMT
    context.user_data["local_amt"] = amt
    await update.message.reply_text("Enter handling fee % (0-99):")
    return P_FEE_PERC


async def get_fee_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee = float(update.message.text); assert 0 <= fee < 100
    except Exception:
        await update.message.reply_text("❌ Percent 0-99 please.")
        return P_FEE_PERC
    context.user_data["fee_perc"] = fee
    await update.message.reply_text("Enter USD amount received:")
    return P_USD_RECEIVED


async def get_usd_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text); assert usd >= 0
    except Exception:
        await update.message.reply_text("❌ Number please.")
        return P_USD_RECEIVED
    context.user_data["usd_amt"] = usd
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="note_skip")]])
    await update.message.reply_text("Enter an optional note or press Skip:", reply_markup=kb)
    return P_NOTE


async def get_payment_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "note_skip":
        await update.callback_query.answer()
        note = ""
    else:
        note = update.message.text.strip()
    context.user_data["note"] = note
    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="date_skip")]])
    prompt = f"Enter payment date DDMMYYYY or press Skip for today ({fmt_date(today)}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return P_DATE


async def get_payment_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "date_skip":
        await update.callback_query.answer()
        date_str = datetime.now().strftime("%d%m%Y")
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, "%d%m%Y")
        except ValueError:
            await update.message.reply_text("❌ Format DDMMYYYY please.")
            return P_DATE
    context.user_data["date"] = date_str
    return await confirm_payment_prompt(update, context)


async def confirm_payment_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    cur = _cust_currency(d["customer_id"])
    fee_amt = d["local_amt"] * d["fee_perc"] / 100
    net     = d["local_amt"] - fee_amt
    fx      = net / d["usd_amt"] if d["usd_amt"] else 0
    summary = (
        f"Local: {fmt_money(d['local_amt'], cur)}\n"
        f"Fee: {d['fee_perc']:.2f}% ({fmt_money(fee_amt, cur)})\n"
        f"USD Recv: {fmt_money(d['usd_amt'], 'USD')}\n"
        f"FX Rate: {fx:.4f}\n"
        f"Note: {d.get('note') or '—'}\n"
        f"Date: {fmt_date(d['date'])}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data="pay_conf_yes"),
                                InlineKeyboardButton("❌ No",  callback_data="pay_conf_no")]])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_CONFIRM


@require_unlock
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "pay_conf_yes":
        await show_payment_menu(update, context)
        return ConversationHandler.END

    d = context.user_data
    fee_amt = d["local_amt"] * d["fee_perc"] / 100
    record = {
        "customer_id": d["customer_id"],
        "local_amt":   d["local_amt"],
        "fee_perc":    d["fee_perc"],
        "fee_amt":     fee_amt,
        "usd_amt":     d["usd_amt"],
        "fx_rate":     (d["local_amt"] - fee_amt) / d["usd_amt"] if d["usd_amt"] else 0,
        "note":        d["note"],
        "date":        d["date"],
        "timestamp":   datetime.utcnow().isoformat(),
    }

    # ── Insert record and log to ledger atomically ──────────────
    pay_id = secure_db.insert("customer_payments", record)
    logger.info("Payment %s inserted", pay_id)

    try:
        add_ledger_entry(
            entry_type="payment",
            action="add",
            customer_id=d["customer_id"],
            related_id=pay_id,
            currency=_cust_currency(d["customer_id"]),
            amount=d["local_amt"],
            note=d["note"],
            date=d["date"],
            details=record,
        )
        logger.info("Payment %s logged to ledger", pay_id)
    except Exception as e:
        logger.error("Ledger error on add – rolling back: %s", e)
        secure_db.remove("customer_payments", [pay_id])
        await update.callback_query.edit_message_text(
            "❌ Failed to log payment — operation rolled back.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]))
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        "✅ Payment recorded.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]))
    return ConversationHandler.END


# ╔══════════════════════════════════════════════════════════════╗
# ║                    VIEW  FLOW                                ║
# ╚══════════════════════════════════════════════════════════════╝
@require_unlock
async def view_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("View all payments (no filter)")
    await update.callback_query.answer()
    rows = secure_db.all("customer_payments")
    if not rows:
        text = "No payments found."
    else:
        lines = []
        for r in rows:
            cust = secure_db.table("customers").get(doc_id=r["customer_id"])
            name = cust["name"] if cust else "Unknown"
            lines.append(f"[{r.doc_id}] {name}: {r['local_amt']:.2f} → {r['usd_amt']:.2f} USD "
                         f"on {fmt_date(r.get('date','01011970'))} | Note: {r.get('note','')}")
        text = "Payments:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)


# ╔══════════════════════════════════════════════════════════════╗
# ║                    EDIT  FLOW                                ║
# ╚══════════════════════════════════════════════════════════════╝
@require_unlock
async def start_edit_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Edit payment – choose customer")
    await update.callback_query.answer()
    rows = secure_db.all("customers")
    if not rows:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"edit_user_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Choose customer:", reply_markup=kb)
    return P_EDIT_CUST


async def list_user_payments_for_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data["customer_id"] = cid
    rows = [r for r in secure_db.all("customer_payments") if r["customer_id"] == cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments for this customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}->{r['usd_amt']:.2f}", callback_data=f"edit_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select payment:", reply_markup=kb)
    return P_EDIT_PAGE


async def get_payment_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    rec = secure_db.table("customer_payments").get(doc_id=pid)
    context.user_data.update({
        "edit_payment": rec,
        "edit_id":      pid,
        "local_amt":    rec["local_amt"],
        "fee_perc":     rec["fee_perc"],
        "usd_amt":      rec["usd_amt"],
        "note":         rec.get("note",""),
        "date":         rec.get("date", datetime.now().strftime("%d%m%Y"))
    })
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_EDIT_LOCAL


async def get_edit_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text); assert amt > 0
    except Exception:
        await update.message.reply_text("❌ Positive number please.")
        return P_EDIT_LOCAL
    context.user_data["local_amt"] = amt
    await update.message.reply_text("Enter new handling fee %:")
    return P_EDIT_FEE


async def get_edit_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee = float(update.message.text); assert 0 <= fee < 100
    except Exception:
        await update.message.reply_text("❌ Percent 0-99 please.")
        return P_EDIT_FEE
    context.user_data["fee_perc"] = fee
    await update.message.reply_text("Enter new USD received:")
    return P_EDIT_USD


async def get_edit_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd = float(update.message.text); assert usd >= 0
    except Exception:
        await update.message.reply_text("❌ Number please.")
        return P_EDIT_USD
    context.user_data["usd_amt"] = usd
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note", callback_data="note_skip")]])
    await update.message.reply_text("Enter optional note or Skip:", reply_markup=kb)
    return P_EDIT_NOTE


async def get_edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "note_skip":
        await update.callback_query.answer()
        note = ""
    else:
        note = update.message.text.strip()
    context.user_data["note"] = note
    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip date", callback_data="edate_skip")]])
    prompt = f"Enter payment date DDMMYYYY or press Skip for today ({fmt_date(today)}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return P_EDIT_DATE


async def get_edit_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "edate_skip":
        await update.callback_query.answer()
        date_str = datetime.now().strftime("%d%m%Y")
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, "%d%m%Y")
        except ValueError:
            await update.message.reply_text("❌ Format DDMMYYYY please.")
            return P_EDIT_DATE
    context.user_data["date"] = date_str
    d = context.user_data
    fee_amt = d["local_amt"] * d["fee_perc"] / 100
    net = d["local_amt"] - fee_amt
    fx  = net / d["usd_amt"] if d["usd_amt"] else 0
    summary = (f"Local: {d['local_amt']:.2f}\n"
               f"Fee: {d['fee_perc']:.2f}% ({fee_amt:.2f})\n"
               f"USD Recv: {d['usd_amt']:.2f}\n"
               f"FX Rate: {fx:.4f}\n"
               f"Note: {d.get('note') or '—'}\n"
               f"Date: {fmt_date(date_str)}")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Save", callback_data="pay_edit_conf_yes"),
                                InlineKeyboardButton("❌ Cancel", callback_data="pay_edit_conf_no")]])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)
    return P_EDIT_CONFIRM


@require_unlock
async def confirm_edit_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "pay_edit_conf_yes":
        await show_payment_menu(update, context)
        return ConversationHandler.END

    d         = context.user_data
    rec_id    = d["edit_id"]
    old_rec   = secure_db.table("customer_payments").get(doc_id=rec_id)
    old_vals  = dict(old_rec)

    # New values
    fee_amt   = d["local_amt"] * d["fee_perc"] / 100
    new_vals  = {
        "customer_id": d["customer_id"],
        "local_amt":   d["local_amt"],
        "fee_perc":    d["fee_perc"],
        "fee_amt":     fee_amt,
        "usd_amt":     d["usd_amt"],
        "fx_rate":     (d["local_amt"] - fee_amt) / d["usd_amt"] if d["usd_amt"] else 0,
        "note":        d["note"],
        "date":        d["date"],
    }

    secure_db.update("customer_payments", new_vals, [rec_id])
    logger.info("Payment %s updated", rec_id)

    try:
        add_ledger_entry(
            entry_type="payment",
            action="edit",
            customer_id=d["customer_id"],
            related_id=rec_id,
            currency=_cust_currency(d["customer_id"]),
            amount=d["local_amt"],
            note=d["note"],
            date=d["date"],
            details={"old": old_vals, "new": new_vals},
        )
        logger.info("Payment %s edit logged", rec_id)
    except Exception as e:
        logger.error("Ledger error on edit – rolling back: %s", e)
        secure_db.update("customer_payments", old_vals, [rec_id])
        await update.callback_query.edit_message_text(
            "❌ Failed to log edit — change rolled back.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]))
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        f"✅ Payment {rec_id} updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]))
    return ConversationHandler.END


# ╔══════════════════════════════════════════════════════════════╗
# ║                    DELETE  FLOW                              ║
# ╚══════════════════════════════════════════════════════════════╝
@require_unlock
async def start_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Delete payment – choose customer")
    await update.callback_query.answer()
    rows = secure_db.all("customers")
    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"del_user_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Choose customer:", reply_markup=kb)
    return P_DEL_CUST


async def list_user_payments_for_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data["customer_id"] = cid
    rows = [r for r in secure_db.all("customer_payments") if r["customer_id"] == cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No payments for this customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}->{r['usd_amt']:.2f}", callback_data=f"del_payment_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select to delete:", reply_markup=kb)
    return P_DEL_PAGE


async def confirm_delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did = int(update.callback_query.data.split("_")[-1])
    context.user_data["delete_id"] = did
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data="pay_del_yes"),
                                InlineKeyboardButton("❌ No", callback_data="pay_del_no")]])
    await update.callback_query.edit_message_text(f"Delete Payment #{did} ?", reply_markup=kb)
    return P_DEL_CONFIRM


@require_unlock
async def confirm_delete_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "pay_del_yes":
        await show_payment_menu(update, context)
        return ConversationHandler.END

    did = context.user_data["delete_id"]
    rec = secure_db.table("customer_payments").get(doc_id=did)
    logger.info("Deleting payment %s", did)

    secure_db.remove("customer_payments", [did])

    try:
        add_ledger_entry(
            entry_type="payment",
            action="delete",
            customer_id=rec["customer_id"],
            related_id=did,
            currency=_cust_currency(rec["customer_id"]),
            amount=rec["local_amt"],
            note=rec.get("note",""),
            date=rec.get("date",""),
            details=rec,
        )
        logger.info("Payment %s deletion logged", did)
    except Exception as e:
        logger.error("Ledger error on delete – rolling back: %s", e)
        secure_db.insert("customer_payments", rec)
        await update.callback_query.edit_message_text(
            "❌ Failed to log delete — action rolled back.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]))
        return ConversationHandler.END

    await update.callback_query.edit_message_text(
        f"✅ Payment {did} deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payment_menu")]]))
    return ConversationHandler.END


# ╔══════════════════════════════════════════════════════════════╗
# ║                REGISTER  ALL  HANDLERS                       ║
# ╚══════════════════════════════════════════════════════════════╝
def register_payment_handlers(app: Application):
    """Attach Payments submenu + all conversations to the Telegram app."""

    # Sub-menu
    app.add_handler(CallbackQueryHandler(show_payment_menu, pattern="^payment_menu$"))

    # ────────────────────── Add conversation ───────────────────────
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add_payment", add_payment),
                      CallbackQueryHandler(add_payment, pattern="^add_payment$")],
        states={
            P_CUST_SELECT:  [CallbackQueryHandler(get_payment_customer, pattern="^pay_cust_")],
            P_LOCAL_AMT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_local_amount)],
            P_FEE_PERC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fee_percent)],
            P_USD_RECEIVED: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_usd_received)],
            P_NOTE:         [CallbackQueryHandler(get_payment_note, pattern="^note_skip$"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_note)],
            P_DATE:         [CallbackQueryHandler(get_payment_date, pattern="^date_skip$"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, get_payment_date)],
            P_CONFIRM:      [CallbackQueryHandler(confirm_payment, pattern="^pay_conf_")],
        },
        fallbacks=[CommandHandler("cancel", payment_back)],
        per_message=False,
    )
    app.add_handler(add_conv)

    # ────────────────────── View conversation ───────────────────────
    app.add_handler(CallbackQueryHandler(view_payments, pattern="^view_payment$"))

    # ────────────────────── Edit conversation ───────────────────────
    edit_conv = ConversationHandler(
        entry_points=[CommandHandler("edit_payment", start_edit_payment),
                      CallbackQueryHandler(start_edit_payment, pattern="^edit_payment$")],
        states={
            P_EDIT_CUST:    [CallbackQueryHandler(list_user_payments_for_edit, pattern="^edit_user_")],
            P_EDIT_PAGE:    [CallbackQueryHandler(get_payment_edit_selection, pattern="^edit_payment_")],
            P_EDIT_LOCAL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_local)],
            P_EDIT_FEE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_fee)],
            P_EDIT_USD:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_usd)],
            P_EDIT_NOTE:    [CallbackQueryHandler(get_edit_note, pattern="^note_skip$"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_note)],
            P_EDIT_DATE:    [CallbackQueryHandler(get_edit_date, pattern="^edate_skip$"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_date)],
            P_EDIT_CONFIRM: [CallbackQueryHandler(confirm_edit_payment, pattern="^pay_edit_conf_")],
        },
        fallbacks=[CommandHandler("cancel", payment_back)],
        per_message=False,
    )
    app.add_handler(edit_conv)

    # ────────────────────── Delete conversation ──────────────────────
    del_conv = ConversationHandler(
        entry_points=[CommandHandler("delete_payment", start_delete_payment),
                      CallbackQueryHandler(start_delete_payment, pattern="^delete_payment$")],
        states={
            P_DEL_CUST:    [CallbackQueryHandler(list_user_payments_for_delete, pattern="^del_user_")],
            P_DEL_PAGE:    [CallbackQueryHandler(confirm_delete_prompt, pattern="^del_payment_")],
            P_DEL_CONFIRM: [CallbackQueryHandler(confirm_delete_payment, pattern="^pay_del_")],
        },
        fallbacks=[CommandHandler("cancel", payment_back)],
        per_message=False,
    )
    app.add_handler(del_conv)
