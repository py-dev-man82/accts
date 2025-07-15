# =========================
#   handlers/expenses.py
# =========================

import logging
logger = logging.getLogger(__name__)
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import add_ledger_entry, delete_ledger_entries_by_related
from secure_db import secure_db

(
    E_ADD_TYPE, E_ADD_ACCT, E_ADD_AMT, E_ADD_CUR, E_ADD_USD, E_ADD_NOTE, E_ADD_DATE, E_ADD_CONFIRM,
    E_VIEW_TYPE, E_VIEW_ACCT, E_VIEW_TIME, E_VIEW_PAGE,
    E_EDIT_TYPE, E_EDIT_ACCT, E_EDIT_TIME, E_EDIT_PAGE, E_EDIT_PICK, E_EDIT_FIELD, E_EDIT_NEWVAL, E_EDIT_CONFIRM,
    E_DEL_TYPE, E_DEL_ACCT, E_DEL_TIME, E_DEL_PAGE, E_DEL_PICK, E_DEL_CONFIRM,
) = range(26) 

ROWS_PER_PAGE = 20

# ---------- SHARED UTIL ----------
async def send_error(update, msg="An error occurred. Please try again."):
    if getattr(update, "message", None):
        await update.message.reply_text(msg)
    elif getattr(update, "callback_query", None):
        await update.callback_query.edit_message_text(msg)

# ---------- MENU ----------
async def show_expense_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Expense",    callback_data="add_expense")],
        [InlineKeyboardButton("👀 View Expenses",  callback_data="view_expense")],
        [InlineKeyboardButton("✏️ Edit Expense",   callback_data="edit_expense")],
        [InlineKeyboardButton("🗑️ Remove Expense", callback_data="delete_expense")],
        [InlineKeyboardButton("🔙 Main Menu",      callback_data="main_menu")],
    ])
    msg = "🧾 Expenses: choose an action"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

# ---------- ADD FLOW ----------
@require_unlock
async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("Entered add_expense (entry point).")
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Store", callback_data="exp_type_store"),
             InlineKeyboardButton("Partner", callback_data="exp_type_partner")],
            [InlineKeyboardButton("Owner", callback_data="exp_type_owner")],
            [InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
        ])
        await update.callback_query.edit_message_text(
            "Expense for which account type?",
            reply_markup=kb
        )
        logger.info("Displayed account type options.")
        return E_ADD_TYPE
    except Exception:
        logger.exception("Error in add_expense handler.")
        await send_error(update)
        return ConversationHandler.END

async def get_expense_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query.data == "main_menu":
            await show_expense_menu(update, context)
            return ConversationHandler.END
        await update.callback_query.answer()
        t = update.callback_query.data.split("_")[-1]
        logger.info(f"get_expense_type fired. User selected: {t}")
        context.user_data["exp_type"] = t
        if t == "store":
            stores = secure_db.all("stores")
            if not stores:
                await update.callback_query.edit_message_text("No stores configured.")
                return ConversationHandler.END
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"exp_acct_{s.doc_id}")]
                 for s in stores] +
                [[InlineKeyboardButton("🔙 Back", callback_data="add_expense"),
                  InlineKeyboardButton("🏠 Home", callback_data="main_menu")]]
            )
            await update.callback_query.edit_message_text("Select store:", reply_markup=kb)
            return E_ADD_ACCT
        elif t == "partner":
            partners = secure_db.all("partners")
            if not partners:
                await update.callback_query.edit_message_text("No partners configured.")
                return ConversationHandler.END
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"{p['name']} ({p['currency']})", callback_data=f"exp_acct_{p.doc_id}")]
                 for p in partners] +
                [[InlineKeyboardButton("🔙 Back", callback_data="add_expense"),
                  InlineKeyboardButton("🏠 Home", callback_data="main_menu")]]
            )
            await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
            return E_ADD_ACCT
        else:  # owner
            context.user_data["exp_acct_id"] = "POT"
            context.user_data["exp_cur"] = "USD"
            await update.callback_query.edit_message_text(
                "Enter amount (in USD):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="add_expense"),
                     InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
                ])
            )
            return E_ADD_AMT
    except Exception:
        logger.exception("Error in get_expense_type handler.")
        await send_error(update)
        return ConversationHandler.END

async def get_expense_acct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query.data == "main_menu":
            await show_expense_menu(update, context)
            return ConversationHandler.END
        if update.callback_query.data == "add_expense":
            return await add_expense(update, context)
        await update.callback_query.answer()
        acct_id = int(update.callback_query.data.split("_")[-1])
        context.user_data["exp_acct_id"] = acct_id
        t = context.user_data["exp_type"]
        if t == "store":
            acct = secure_db.table("stores").get(doc_id=acct_id)
        else:
            acct = secure_db.table("partners").get(doc_id=acct_id)
        cur = acct.get("currency", "USD")
        context.user_data["exp_cur"] = cur
        await update.callback_query.edit_message_text(
            f"Enter amount (in {cur}):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="add_expense"),
                 InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
            ])
        )
        return E_ADD_AMT
    except Exception:
        logger.exception("Error in get_expense_acct handler.")
        await send_error(update)
        return ConversationHandler.END

async def get_expense_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        if text.lower() == "back":
            return await get_expense_acct(update, context)
        amt = float(text)
        assert amt > 0
        context.user_data["exp_amt"] = amt
        await update.message.reply_text(
            "Enter fee % (0 for none):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="add_expense"),
                 InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
            ])
        )
        return E_ADD_CUR
    except Exception:
        logger.exception("Invalid or non-positive amount in get_expense_amt.")
        await send_error(update, "Enter a positive number.")
        return E_ADD_AMT

async def get_expense_cur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        if text.lower() == "back":
            return await get_expense_amt(update, context)
        fee = float(text)
        assert 0 <= fee < 100
        context.user_data["exp_fee_perc"] = fee
        await update.message.reply_text(
            f"Enter USD amount (or 0 if N/A):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="add_expense"),
                 InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
            ])
        )
        return E_ADD_USD
    except Exception:
        logger.exception("Invalid fee % in get_expense_cur.")
        await send_error(update, "Enter a valid percent (0-99).")
        return E_ADD_CUR

async def get_expense_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        if text.lower() == "back":
            return await get_expense_cur(update, context)
        usd_amt = float(text)
        assert usd_amt >= 0
        context.user_data["exp_usd_amt"] = usd_amt
        amt = context.user_data["exp_amt"]
        fee = context.user_data["exp_fee_perc"]
        net = amt - (amt * fee / 100)
        fx = (net / usd_amt) if usd_amt else 0
        context.user_data["exp_fx"] = fx
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➖ Skip note", callback_data="exp_note_skip")],
            [InlineKeyboardButton("🔙 Back", callback_data="add_expense"),
             InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
        ])
        await update.message.reply_text("Enter an optional note or Skip:", reply_markup=kb)
        return E_ADD_NOTE
    except Exception:
        logger.exception("Invalid USD in get_expense_usd.")
        await send_error(update, "Enter a valid USD amount (or 0).")
        return E_ADD_USD


async def get_expense_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        if text.lower() == "back":
            return await get_expense_cur(update, context)
        usd_amt = float(text)
        assert usd_amt >= 0
        context.user_data["exp_usd_amt"] = usd_amt
        amt = context.user_data["exp_amt"]
        fee = context.user_data["exp_fee_perc"]
        net = amt - (amt * fee / 100)
        fx = (net / usd_amt) if usd_amt else 0
        context.user_data["exp_fx"] = fx
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➖ Skip note", callback_data="exp_note_skip")],
            [InlineKeyboardButton("🔙 Back", callback_data="add_expense"),
             InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
        ])
        await update.message.reply_text("Enter an optional note or Skip:", reply_markup=kb)
        return E_ADD_NOTE
    except Exception:
        logger.exception("Invalid USD in get_expense_note.")
        await send_error(update, "Enter a valid USD amount (or 0).")
        return E_ADD_NOTE

async def get_expense_note_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query:
            if update.callback_query.data == "main_menu":
                await show_expense_menu(update, context)
                return ConversationHandler.END
            if update.callback_query.data == "add_expense":
                return await add_expense(update, context)
            if update.callback_query.data == "exp_note_skip":
                note = ""
            else:
                note = ""
        else:
            note = update.message.text.strip()
        context.user_data["exp_note"] = note
        today = datetime.now().strftime("%d%m%Y")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Skip", callback_data="exp_date_skip")],
            [InlineKeyboardButton("🔙 Back", callback_data="add_expense"),
             InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
        ])
        prompt = f"Enter expense date DDMMYYYY or Skip for today ({today}):"
        if update.callback_query:
            await update.callback_query.edit_message_text(prompt, reply_markup=kb)
        else:
            await update.message.reply_text(prompt, reply_markup=kb)
        return E_ADD_DATE
    except Exception:
        logger.exception("Error in get_expense_note_final handler.")
        await send_error(update)
        return E_ADD_NOTE

async def get_expense_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query:
            if update.callback_query.data == "main_menu":
                await show_expense_menu(update, context)
                return ConversationHandler.END
            if update.callback_query.data == "add_expense":
                return await add_expense(update, context)
            if update.callback_query.data == "exp_date_skip":
                date_str = datetime.now().strftime("%d%m%Y")
            else:
                date_str = ""
        else:
            date_str = update.message.text.strip()
            try:
                datetime.strptime(date_str, "%d%m%Y")
            except Exception:
                await update.message.reply_text("Format DDMMYYYY, please.")
                return E_ADD_DATE
        context.user_data["exp_date"] = date_str or datetime.now().strftime("%d%m%Y")

        d = context.user_data
        acct_label = d["exp_type"].capitalize()
        acct_id = d["exp_acct_id"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data="exp_save_yes"),
             InlineKeyboardButton("❌ No",  callback_data="exp_save_no")],
            [InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
        ])
        cur = d.get("exp_cur", "USD")
        summary = (
            f"Account: {acct_label}\n"
            f"Account ID: {acct_id}\n"
            f"Amount: {fmt_money(d['exp_amt'], cur)}\n"
            f"Fee: {d.get('exp_fee_perc',0):.2f}%\n"
            f"USD Amt: {fmt_money(d.get('exp_usd_amt',0),'USD')}\n"
            f"FX: {d.get('exp_fx',0):.4f}\n"
            f"Note: {d.get('exp_note','') or '—'}\n"
            f"Date: {fmt_date(d['exp_date'])}\n\nConfirm?"
        )
        if update.message:
            await update.message.reply_text(summary, reply_markup=kb)
        elif update.callback_query:
            await update.callback_query.edit_message_text(summary, reply_markup=kb)
        return E_ADD_CONFIRM
    except Exception:
        logger.exception("Error in get_expense_date handler.")
        await send_error(update)
        return ConversationHandler.END

@require_unlock
async def confirm_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer()
        if update.callback_query.data == "main_menu":
            await show_expense_menu(update, context)
            return ConversationHandler.END
        if update.callback_query.data != "exp_save_yes":
            await show_expense_menu(update, context)
            return ConversationHandler.END

        d = context.user_data
        record = {
            "account_type": d["exp_type"],
            "account_id": d["exp_acct_id"],
            "amount": d["exp_amt"],
            "fee_perc": d.get("exp_fee_perc", 0),
            "usd_amt": d.get("exp_usd_amt", 0),
            "fx_rate": d.get("exp_fx", 0),
            "currency": d.get("exp_cur", "USD"),
            "note": d.get("exp_note", ""),
            "date": d["exp_date"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        expense_id = None
        related_id = None
        try:
            related_id = add_ledger_entry(
                account_type=d["exp_type"],
                account_id=d["exp_acct_id"],
                entry_type="expense",
                related_id=None,
                amount=-abs(d["exp_amt"]),
                currency=d["exp_cur"],
                note=record.get("note", ""),
                date=d["exp_date"],
                timestamp=record["timestamp"],
                fee_perc=d.get("exp_fee_perc", 0),
                usd_amt=d.get("exp_usd_amt", 0),
                fx_rate=d.get("exp_fx", 0),
            )
            record["related_id"] = related_id
            expense_id = secure_db.insert("expenses", record)
        except Exception as e:
            if related_id is not None:
                delete_ledger_entries_by_related(d["exp_type"], d["exp_acct_id"], related_id)
            logger.exception("confirm_expense: failed writing to ledger/DB")
            await update.callback_query.edit_message_text(
                f"❌ Expense not recorded, error writing to ledger: {e}"
            )
            return ConversationHandler.END

        await update.callback_query.edit_message_text(
            "✅ Expense recorded.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="expense_menu")]])
        )
        logger.info("confirm_expense: expense recorded successfully.")
        return ConversationHandler.END
    except Exception:
        logger.exception("Error in confirm_expense handler.")
        await send_error(update)
        return ConversationHandler.END

# ---------- VIEW FLOW ----------
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

async def view_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Store", callback_data="exp_view_type_store"),
         InlineKeyboardButton("Partner", callback_data="exp_view_type_partner")],
        [InlineKeyboardButton("Owner", callback_data="exp_view_type_owner")],
        [InlineKeyboardButton("🔙 Back", callback_data="expense_menu")]
    ])
    await update.callback_query.edit_message_text("View expenses for which account type?", reply_markup=kb)
    return E_VIEW_TYPE

async def get_view_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    t = update.callback_query.data.split("_")[-1]
    context.user_data["view_type"] = t
    if t == "store":
        stores = secure_db.all("stores")
        if not stores:
            await update.callback_query.edit_message_text("No stores configured.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"exp_view_acct_{s.doc_id}")]
            for s in stores
        ])
        await update.callback_query.edit_message_text("Select store:", reply_markup=kb)
        return E_VIEW_ACCT
    elif t == "partner":
        partners = secure_db.all("partners")
        if not partners:
            await update.callback_query.edit_message_text("No partners configured.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{p['name']} ({p['currency']})", callback_data=f"exp_view_acct_{p.doc_id}")]
            for p in partners
        ])
        await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
        return E_VIEW_ACCT
    else:  # owner
        context.user_data["view_acct_id"] = "POT"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Last 3 months", callback_data="exp_view_time_3m")],
            [InlineKeyboardButton("Last 6 months", callback_data="exp_view_time_6m")],
            [InlineKeyboardButton("All", callback_data="exp_view_time_all")],
            [InlineKeyboardButton("🔙 Back", callback_data="view_expense")]
        ])
        await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
        return E_VIEW_TIME

async def get_view_acct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    acct_id = int(update.callback_query.data.split("_")[-1])
    context.user_data["view_acct_id"] = acct_id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Last 3 months", callback_data="exp_view_time_3m")],
        [InlineKeyboardButton("Last 6 months", callback_data="exp_view_time_6m")],
        [InlineKeyboardButton("All", callback_data="exp_view_time_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="view_expense")]
    ])
    await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
    return E_VIEW_TIME

async def get_view_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    time_str = update.callback_query.data.split("_")[-1]
    context.user_data["view_time"] = time_str
    context.user_data["view_page"] = 1
    return await render_expense_page(update, context)

async def render_expense_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    typ = context.user_data["view_type"]
    aid = context.user_data["view_acct_id"]
    time_str = context.user_data["view_time"]
    page = context.user_data["view_page"]

    rows = [r for r in secure_db.all("expenses") if r["account_type"] == typ and str(r["account_id"]) == str(aid)]
    if time_str != "all":
        months = int(time_str.replace("m", ""))
        rows = _months_filter(rows, months)
    rows.sort(key=lambda r: (r.get("date","01011970"), r.get("timestamp","")), reverse=True)

    total = len(rows)
    start, end = (page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No expenses for that period."
    else:
        lines = [
            f"{str(r.get('related_id', r.doc_id))}: {fmt_date(r.get('date',''))} {fmt_money(r['amount'], r['currency'])} | Fee: {r.get('fee_perc',0):.2f}% | USD: {fmt_money(r.get('usd_amt',0),'USD')} | FX: {r.get('fx_rate',0):.4f} | {r.get('note','')}"
            for r in chunk
        ]
        text = (f"🧾 Expenses  P{page}/"
                f"{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
                + "\n".join(lines) +
                "\n\nReply with reference number (leftmost) or use ⬅️➡️")
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="exp_view_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="exp_view_next"))
    kb = InlineKeyboardMarkup([nav,
                               [InlineKeyboardButton("🔙 Back", callback_data="expense_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return E_VIEW_PAGE

async def view_paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_page"] += (
        -1 if update.callback_query.data.endswith("prev") else 1
    )
    return await render_expense_page(update, context)

# ---------- EDIT FLOW ----------
@require_unlock
async def edit_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Store", callback_data="exp_edit_type_store"),
         InlineKeyboardButton("Partner", callback_data="exp_edit_type_partner")],
        [InlineKeyboardButton("Owner", callback_data="exp_edit_type_owner")],
        [InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
    ])
    await update.callback_query.edit_message_text("Edit expenses for which account type?", reply_markup=kb)
    return E_EDIT_TYPE

async def edit_get_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "main_menu":
        await show_expense_menu(update, context)
        return ConversationHandler.END
    t = update.callback_query.data.split("_")[-1]
    context.user_data["edit_type"] = t
    if t == "store":
        stores = secure_db.all("stores")
        if not stores:
            await update.callback_query.edit_message_text("No stores configured.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"exp_edit_acct_{s.doc_id}")] for s in stores] +
            [[InlineKeyboardButton("🔙 Back", callback_data="edit_expense_start"),
              InlineKeyboardButton("🏠 Home", callback_data="main_menu")]]
        )
        await update.callback_query.edit_message_text("Select store:", reply_markup=kb)
        return E_EDIT_ACCT
    elif t == "partner":
        partners = secure_db.all("partners")
        if not partners:
            await update.callback_query.edit_message_text("No partners configured.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{p['name']} ({p['currency']})", callback_data=f"exp_edit_acct_{p.doc_id}")] for p in partners] +
            [[InlineKeyboardButton("🔙 Back", callback_data="edit_expense_start"),
              InlineKeyboardButton("🏠 Home", callback_data="main_menu")]]
        )
        await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
        return E_EDIT_ACCT
    else:  # owner
        context.user_data["edit_acct_id"] = "POT"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Last 3 months", callback_data="exp_edit_time_3m")],
            [InlineKeyboardButton("Last 6 months", callback_data="exp_edit_time_6m")],
            [InlineKeyboardButton("All", callback_data="exp_edit_time_all")],
            [InlineKeyboardButton("🔙 Back", callback_data="edit_expense_start"),
             InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
        ])
        await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
        return E_EDIT_TIME

async def edit_get_acct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "main_menu":
        await show_expense_menu(update, context)
        return ConversationHandler.END
    if update.callback_query.data == "edit_expense_start":
        return await edit_expense_start(update, context)
    acct_id = int(update.callback_query.data.split("_")[-1])
    context.user_data["edit_acct_id"] = acct_id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Last 3 months", callback_data="exp_edit_time_3m")],
        [InlineKeyboardButton("Last 6 months", callback_data="exp_edit_time_6m")],
        [InlineKeyboardButton("All", callback_data="exp_edit_time_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="edit_expense_start"),
         InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
    ])
    await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
    return E_EDIT_TIME

async def edit_get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "main_menu":
        await show_expense_menu(update, context)
        return ConversationHandler.END
    if update.callback_query.data == "edit_expense_start":
        return await edit_expense_start(update, context)
    time_str = update.callback_query.data.split("_")[-1]
    context.user_data["edit_time"] = time_str
    context.user_data["edit_page"] = 1
    return await render_edit_expense_page(update, context)

async def render_edit_expense_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    typ = context.user_data["edit_type"]
    aid = context.user_data["edit_acct_id"]
    time_str = context.user_data["edit_time"]
    page = context.user_data["edit_page"]

    rows = [r for r in secure_db.all("expenses") if r["account_type"] == typ and str(r["account_id"]) == str(aid)]
    if time_str != "all":
        months = int(time_str.replace("m", ""))
        rows = _months_filter(rows, months)
    rows.sort(key=lambda r: (r.get("date","01011970"), r.get("timestamp","")), reverse=True)

    total = len(rows)
    start, end = (page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No expenses for that period."
    else:
        lines = [
            f"{str(r.get('related_id', r.doc_id))}: {fmt_date(r.get('date',''))} {fmt_money(r['amount'], r['currency'])} | Fee: {r.get('fee_perc',0):.2f}% | USD: {fmt_money(r.get('usd_amt',0),'USD')} | FX: {r.get('fx_rate',0):.4f} | {r.get('note','')}"
            for r in chunk
        ]
        text = (f"✏️ Edit Expenses  P{page}/"
                f"{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
                + "\n".join(lines) +
                "\n\nReply with reference number (leftmost) or use ⬅️➡️")
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="exp_edit_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="exp_edit_next"))
    nav.append(InlineKeyboardButton("🏠 Home", callback_data="main_menu"))
    kb = InlineKeyboardMarkup([nav,
                               [InlineKeyboardButton("🔙 Back", callback_data="edit_expense_start")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return E_EDIT_PAGE

async def edit_paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "main_menu":
        await show_expense_menu(update, context)
        return ConversationHandler.END
    if update.callback_query.data == "edit_expense_start":
        return await edit_expense_start(update, context)
    context.user_data["edit_page"] += (
        -1 if update.callback_query.data.endswith("prev") else 1
    )
    return await render_edit_expense_page(update, context)

async def edit_pick_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rid = int(update.message.text.strip())
        q = Query()
        rec = secure_db.table("expenses").get(
            (q.related_id == rid) | (q.related_id == str(rid)) | (q.doc_id == rid)
        )
        assert rec and rec["account_type"] == context.user_data["edit_type"] and str(rec["account_id"]) == str(context.user_data["edit_acct_id"])
    except Exception:
        await send_error(update, "❌ Invalid reference number; try again:")
        return E_EDIT_PAGE
    context.user_data["edit_rec"] = rec
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Amount", callback_data="edit_field_amt")],
        [InlineKeyboardButton("Fee %", callback_data="edit_field_fee")],
        [InlineKeyboardButton("USD Amt", callback_data="edit_field_usd")],
        [InlineKeyboardButton("Note", callback_data="edit_field_note")],
        [InlineKeyboardButton("Date", callback_data="edit_field_date")],
        [InlineKeyboardButton("🔙 Back", callback_data="edit_expense_start"),
         InlineKeyboardButton("🏠 Home", callback_data="main_menu")],
    ])
    await update.message.reply_text("Editing expense. Choose field:", reply_markup=kb)
    return E_EDIT_FIELD

async def edit_choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    field = update.callback_query.data.split("_")[-1]
    context.user_data["edit_field"] = field
    if field == "amt":
        await update.callback_query.edit_message_text("New amount (positive number):")
    elif field == "fee":
        await update.callback_query.edit_message_text("New fee percent (0-99):")
    elif field == "usd":
        await update.callback_query.edit_message_text("New USD amount (>=0):")
    elif field == "note":
        await update.callback_query.edit_message_text("New note (or '-' to clear):")
    elif field == "date":
        today = datetime.now().strftime("%d%m%Y")
        await update.callback_query.edit_message_text(f"New date DDMMYYYY (today {today}):")
    return E_EDIT_NEWVAL


async def edit_newval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data["edit_field"]
    new = update.message.text.strip()
    if field == "amt":
        try:
            amt = float(new)
            assert amt > 0
            context.user_data["new_val"] = amt
        except Exception:
            await send_error(update, "Invalid amount.")
            return E_EDIT_NEWVAL
    elif field == "fee":
        try:
            fee = float(new)
            assert 0 <= fee < 100
            context.user_data["new_val"] = fee
        except Exception:
            await send_error(update, "Invalid fee percent.")
            return E_EDIT_NEWVAL
    elif field == "usd":
        try:
            usd = float(new)
            assert usd >= 0
            context.user_data["new_val"] = usd
        except Exception:
            await send_error(update, "Invalid USD amount.")
            return E_EDIT_NEWVAL
    elif field == "note":
        context.user_data["new_val"] = "" if new == "-" else new
    elif field == "date":
        try:
            datetime.strptime(new, "%d%m%Y")
            context.user_data["new_val"] = new
        except Exception:
            await send_error(update, "Invalid date format.")
            return E_EDIT_NEWVAL
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="edit_exp_conf_yes"),
         InlineKeyboardButton("❌ No", callback_data="edit_exp_conf_no")],
        [InlineKeyboardButton("🏠 Home", callback_data="main_menu")]
    ])
    await update.message.reply_text(
        f"Change **{field}** to `{context.user_data['new_val']}` ?",
        reply_markup=kb
    )
    return E_EDIT_CONFIRM


@require_unlock
async def edit_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "main_menu":
        await show_expense_menu(update, context)
        return ConversationHandler.END
    if not update.callback_query.data.endswith("_yes"):
        await show_expense_menu(update, context)
        return ConversationHandler.END
    rec = context.user_data["edit_rec"]
    related_id = rec.get("related_id", rec.doc_id)
    eid = rec.doc_id
    field = context.user_data["edit_field"]
    new = context.user_data["new_val"]

    update_dict = {}
    if field == "amt":
        update_dict["amount"] = new
    elif field == "fee":
        update_dict["fee_perc"] = new
    elif field == "usd":
        update_dict["usd_amt"] = new
    elif field == "note":
        update_dict["note"] = new
    elif field == "date":
        update_dict["date"] = new

    # recalc fx if necessary
    if "amount" in update_dict or "fee_perc" in update_dict or "usd_amt" in update_dict:
        amt = update_dict.get("amount", rec["amount"])
        fee = update_dict.get("fee_perc", rec.get("fee_perc", 0))
        usd = update_dict.get("usd_amt", rec.get("usd_amt", 0))
        net = amt - (amt * fee / 100)
        fx = (net / usd) if usd else 0
        update_dict["fx_rate"] = fx

    try:
        secure_db.update("expenses", update_dict, [eid])
        delete_ledger_entries_by_related(rec["account_type"], rec["account_id"], related_id)
        rec = {**rec, **update_dict}
        add_ledger_entry(
            account_type=rec["account_type"],
            account_id=rec["account_id"],
            entry_type="expense",
            related_id=related_id,
            amount=-abs(rec["amount"]),
            currency=rec["currency"],
            note=rec.get("note", ""),
            date=rec.get("date", ""),
            timestamp=rec.get("timestamp", ""),
            fee_perc=rec.get("fee_perc", 0),
            usd_amt=rec.get("usd_amt", 0),
            fx_rate=rec.get("fx_rate", 0),
        )
    except Exception as e:
        logger.error(f"Failed to update expense: {e}")
        await send_error(update, "❌ Error updating expense.")
        return ConversationHandler.END

    await update.callback_query.edit_message_text("✅ Expense updated.")
    return ConversationHandler.END

# ---------- DELETE FLOW ----------
@require_unlock
async def delete_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Store", callback_data="exp_del_type_store"),
         InlineKeyboardButton("Partner", callback_data="exp_del_type_partner")],
        [InlineKeyboardButton("Owner", callback_data="exp_del_type_owner")],
        [InlineKeyboardButton("🔙 Back", callback_data="expense_menu")]
    ])
    await update.callback_query.edit_message_text("Delete expenses for which account type?", reply_markup=kb)
    return E_DEL_TYPE

async def del_get_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    t = update.callback_query.data.split("_")[-1]
    context.user_data["del_type"] = t
    if t == "store":
        stores = secure_db.all("stores")
        if not stores:
            await update.callback_query.edit_message_text("No stores configured.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"exp_del_acct_{s.doc_id}")] for s in stores
        ])
        await update.callback_query.edit_message_text("Select store:", reply_markup=kb)
        return E_DEL_ACCT
    elif t == "partner":
        partners = secure_db.all("partners")
        if not partners:
            await update.callback_query.edit_message_text("No partners configured.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{p['name']} ({p['currency']})", callback_data=f"exp_del_acct_{p.doc_id}")] for p in partners
        ])
        await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
        return E_DEL_ACCT
    else:  # owner
        context.user_data["del_acct_id"] = "POT"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Last 3 months", callback_data="exp_del_time_3m")],
            [InlineKeyboardButton("Last 6 months", callback_data="exp_del_time_6m")],
            [InlineKeyboardButton("All", callback_data="exp_del_time_all")],
            [InlineKeyboardButton("🔙 Back", callback_data="delete_expense")]
        ])
        await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
        return E_DEL_TIME

async def del_get_acct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    acct_id = int(update.callback_query.data.split("_")[-1])
    context.user_data["del_acct_id"] = acct_id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Last 3 months", callback_data="exp_del_time_3m")],
        [InlineKeyboardButton("Last 6 months", callback_data="exp_del_time_6m")],
        [InlineKeyboardButton("All", callback_data="exp_del_time_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="delete_expense")]
    ])
    await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
    return E_DEL_TIME

async def del_get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    time_str = update.callback_query.data.split("_")[-1]
    context.user_data["del_time"] = time_str
    context.user_data["del_page"] = 1
    return await render_delete_expense_page(update, context)

async def render_delete_expense_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    typ = context.user_data["del_type"]
    aid = context.user_data["del_acct_id"]
    time_str = context.user_data["del_time"]
    page = context.user_data["del_page"]

    rows = [r for r in secure_db.all("expenses") if r["account_type"] == typ and str(r["account_id"]) == str(aid)]
    if time_str != "all":
        months = int(time_str.replace("m", ""))
        rows = _months_filter(rows, months)
    rows.sort(key=lambda r: (r.get("date","01011970"), r.get("timestamp","")), reverse=True)

    total = len(rows)
    start, end = (page-1)*ROWS_PER_PAGE, page*ROWS_PER_PAGE
    chunk = rows[start:end]

    if not chunk:
        text = "No expenses for that period."
    else:
        lines = [
            f"{str(r.get('related_id', r.doc_id))}: {fmt_date(r.get('date',''))} {fmt_money(r['amount'], r['currency'])} | Fee: {r.get('fee_perc',0):.2f}% | USD: {fmt_money(r.get('usd_amt',0),'USD')} | FX: {r.get('fx_rate',0):.4f} | {r.get('note','')}"
            for r in chunk
        ]
        text = (f"🗑️ Delete Expenses  P{page}/"
                f"{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
                + "\n".join(lines) +
                "\n\nReply with reference number (leftmost) or use ⬅️➡️")
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="exp_del_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="exp_del_next"))
    kb = InlineKeyboardMarkup([nav,
                               [InlineKeyboardButton("🔙 Back", callback_data="delete_expense")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return E_DEL_PAGE

async def del_paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["del_page"] += (
        -1 if update.callback_query.data.endswith("prev") else 1
    )
    return await render_delete_expense_page(update, context)

async def del_pick_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rid = int(update.message.text.strip())
        q = Query()
        rec = secure_db.table("expenses").get(
            (q.related_id == rid) | (q.related_id == str(rid)) | (q.doc_id == rid)
        )
        assert rec and rec["account_type"] == context.user_data["del_type"] and str(rec["account_id"]) == str(context.user_data["del_acct_id"])
    except Exception:
        await send_error(update, "❌ Invalid reference number; try again:")
        return E_DEL_PAGE
    context.user_data["del_rec"] = rec
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Delete", callback_data="del_exp_conf_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="del_exp_conf_no")]
    ])
    await update.message.reply_text(
        f"Delete expense {str(rec.get('related_id', rec.doc_id))}: {fmt_date(rec.get('date',''))} {fmt_money(rec['amount'], rec['currency'])}?",
        reply_markup=kb
    )
    return E_DEL_CONFIRM

@require_unlock
async def del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if not update.callback_query.data.endswith("_yes"):
        await show_expense_menu(update, context)
        return ConversationHandler.END
    rec = context.user_data["del_rec"]
    related_id = rec.get("related_id", rec.doc_id)
    eid = rec.doc_id
    try:
        secure_db.remove("expenses", [eid])
        delete_ledger_entries_by_related(rec["account_type"], rec["account_id"], related_id)
    except Exception as e:
        logger.error(f"Failed to delete expense: {e}")
        await send_error(update, "❌ Error deleting expense.")
        return ConversationHandler.END

    await update.callback_query.edit_message_text("✅ Expense deleted.")
    return ConversationHandler.END

# ---------- REGISTER HANDLERS ----------
def register_expense_handlers(app):
    # Top-level callbacks (menu + main buttons)
    app.add_handler(CallbackQueryHandler(show_expense_menu, pattern="^expense_menu$"))
    app.add_handler(CallbackQueryHandler(view_expense_start, pattern="^view_expense$"))
    app.add_handler(CallbackQueryHandler(edit_expense_start, pattern="^edit_expense$"))
    app.add_handler(CallbackQueryHandler(delete_expense_start, pattern="^delete_expense$"))
    app.add_handler(CallbackQueryHandler(view_paginate, pattern="^exp_view_prev$|^exp_view_next$"))
    app.add_handler(CallbackQueryHandler(edit_paginate, pattern="^exp_edit_prev$|^exp_edit_next$"))
    app.add_handler(CallbackQueryHandler(del_paginate, pattern="^exp_del_prev$|^exp_del_next$"))

    # --- Add Flow ---
    add_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_expense, pattern="^add_expense$"),
        ],
        states={
            E_ADD_TYPE:   [CallbackQueryHandler(get_expense_type, pattern="^exp_type_")],
            E_ADD_ACCT:   [CallbackQueryHandler(get_expense_acct, pattern="^exp_acct_")],
            E_ADD_AMT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_expense_amt)],
            E_ADD_CUR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_expense_cur)],
            E_ADD_USD:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_expense_usd)],
            E_ADD_NOTE:   [
                CallbackQueryHandler(get_expense_note_final, pattern="^exp_note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_expense_note_final),
            ],
            E_ADD_DATE:   [
                CallbackQueryHandler(get_expense_date, pattern="^exp_date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_expense_date),
            ],
            E_ADD_CONFIRM: [CallbackQueryHandler(confirm_expense, pattern="^exp_save_")],
        },
        fallbacks=[],
        allow_reentry=True,
)
    app.add_handler(add_conv)

    # --- View Flow ---
    view_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(view_expense_start, pattern="^view_expense$")],
        states={
            E_VIEW_TYPE: [CallbackQueryHandler(get_view_type, pattern="^exp_view_type_")],
            E_VIEW_ACCT: [CallbackQueryHandler(get_view_acct, pattern="^exp_view_acct_")],
            E_VIEW_TIME: [CallbackQueryHandler(get_view_time, pattern="^exp_view_time_")],
            E_VIEW_PAGE: [CallbackQueryHandler(view_paginate, pattern="^exp_view_prev$|^exp_view_next$")],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(view_conv)

    # --- Edit Flow ---
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_expense_start, pattern="^edit_expense$")],
        states={
            E_EDIT_TYPE:   [CallbackQueryHandler(edit_get_type, pattern="^exp_edit_type_")],
            E_EDIT_ACCT:   [CallbackQueryHandler(edit_get_acct, pattern="^exp_edit_acct_")],
            E_EDIT_TIME:   [CallbackQueryHandler(edit_get_time, pattern="^exp_edit_time_")],
            E_EDIT_PAGE:   [
                CallbackQueryHandler(edit_paginate, pattern="^exp_edit_prev$|^exp_edit_next$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_pick_expense)
            ],
            E_EDIT_FIELD:  [CallbackQueryHandler(edit_choose_field, pattern="^edit_field_")],
            E_EDIT_NEWVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_newval)],
            E_EDIT_CONFIRM: [CallbackQueryHandler(edit_confirm, pattern="^edit_exp_conf_")],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(edit_conv)

    # --- Delete Flow ---
    del_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_expense_start, pattern="^delete_expense$")],
        states={
            E_DEL_TYPE: [CallbackQueryHandler(del_get_type, pattern="^exp_del_type_")],
            E_DEL_ACCT: [CallbackQueryHandler(del_get_acct, pattern="^exp_del_acct_")],
            E_DEL_TIME: [CallbackQueryHandler(del_get_time, pattern="^exp_del_time_")],
            E_DEL_PAGE: [
                CallbackQueryHandler(del_paginate, pattern="^exp_del_prev$|^exp_del_next$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, del_pick_expense)
            ],
            E_DEL_CONFIRM: [CallbackQueryHandler(del_confirm, pattern="^del_exp_conf_")],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(del_conv)

