# handlers/expenses.py

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
    E_ADD_TYPE, E_ADD_ACCT, E_ADD_AMT, E_ADD_CUR, E_ADD_NOTE, E_ADD_CAT, E_ADD_DATE, E_ADD_CONFIRM,
    E_VIEW_TYPE, E_VIEW_ACCT, E_VIEW_TIME, E_VIEW_PAGE,
    E_EDIT_TYPE, E_EDIT_ACCT, E_EDIT_TIME, E_EDIT_PAGE, E_EDIT_PICK, E_EDIT_FIELD, E_EDIT_NEWVAL, E_EDIT_CONFIRM,
    E_DEL_TYPE, E_DEL_ACCT, E_DEL_TIME, E_DEL_PAGE, E_DEL_PICK, E_DEL_CONFIRM,
) = range(26)

EXPENSE_CATS = ["Other"]
ROWS_PER_PAGE = 20

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
            [InlineKeyboardButton("Owner", callback_data="exp_type_owner")]
        ])
        await update.callback_query.edit_message_text("Expense for which account type?", reply_markup=kb)
        logger.info("Displayed account type options.")
        return E_ADD_TYPE
    except Exception:
        logger.exception("Error in add_expense handler.")
        await send_error(update)
        return ConversationHandler.END

async def get_expense_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer()
        t = update.callback_query.data.split("_")[-1]
        logger.info(f"get_expense_type fired. User selected: {t}")
        context.user_data["exp_type"] = t
        if t == "store":
            stores = secure_db.all("stores")
            logger.info(f"Found {len(stores)} stores.")
            if not stores:
                await update.callback_query.edit_message_text("No stores configured.")
                return ConversationHandler.END
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"exp_acct_{s.doc_id}")]
                for s in stores
            ])
            await update.callback_query.edit_message_text("Select store:", reply_markup=kb)
            return E_ADD_ACCT
        elif t == "partner":
            partners = secure_db.all("partners")
            logger.info(f"Found {len(partners)} partners.")
            if not partners:
                await update.callback_query.edit_message_text("No partners configured.")
                return ConversationHandler.END
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{p['name']} ({p['currency']})", callback_data=f"exp_acct_{p.doc_id}")]
                for p in partners
            ])
            await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
            return E_ADD_ACCT
        else:  # owner
            context.user_data["exp_acct_id"] = "POT"
            logger.info("Account type: owner. Prompting for amount.")
            await update.callback_query.edit_message_text("Enter amount (numeric):")
            return E_ADD_AMT
    except Exception:
        logger.exception("Error in get_expense_type handler.")
        await send_error(update)
        return ConversationHandler.END

async def get_expense_acct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer()
        acct_id = int(update.callback_query.data.split("_")[-1])
        logger.info(f"get_expense_acct fired. Account selected: {acct_id}")
        context.user_data["exp_acct_id"] = acct_id
        await update.callback_query.edit_message_text("Enter amount (numeric):")
        return E_ADD_AMT
    except Exception:
        logger.exception("Error in get_expense_acct handler.")
        await send_error(update)
        return ConversationHandler.END

async def get_expense_amt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text)
        assert amt > 0
        context.user_data["exp_amt"] = amt
        logger.info(f"get_expense_amt fired. Amount entered: {amt}")
        await update.message.reply_text("Enter currency code (e.g. USD):")
        return E_ADD_CUR
    except Exception:
        logger.exception("Invalid or non-positive amount in get_expense_amt.")
        await send_error(update, "Enter a positive number.")
        return E_ADD_AMT

async def get_expense_cur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cur = update.message.text.strip().upper()
        context.user_data["exp_cur"] = cur
        logger.info(f"get_expense_cur fired. Currency entered: {cur}")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="exp_note_skip")]])
        await update.message.reply_text("Optional note (or Skip):", reply_markup=kb)
        return E_ADD_NOTE
    except Exception:
        logger.exception("Error in get_expense_cur handler.")
        await send_error(update)
        return E_ADD_CUR

async def get_expense_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query and update.callback_query.data == "exp_note_skip":
            await update.callback_query.answer()
            note = ""
            logger.info("get_expense_note: skipped note.")
        else:
            note = update.message.text.strip()
            logger.info(f"get_expense_note: note entered: {note}")
        context.user_data["exp_note"] = note
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(cat, callback_data=f"exp_cat_{cat.lower()}")] for cat in EXPENSE_CATS])
        await update.message.reply_text("Choose category:", reply_markup=kb)
        return E_ADD_CAT
    except Exception:
        logger.exception("Error in get_expense_note handler.")
        await send_error(update)
        return E_ADD_NOTE

async def get_expense_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer()
        cat = update.callback_query.data.split("_")[-1].capitalize()
        context.user_data["exp_cat"] = cat
        logger.info(f"get_expense_cat fired. Category chosen: {cat}")
        today = datetime.now().strftime("%d%m%Y")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip", callback_data="exp_date_skip")]])
        prompt = f"Enter expense date DDMMYYYY or Skip for today ({today}):"
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
        return E_ADD_DATE
    except Exception:
        logger.exception("Error in get_expense_cat handler.")
        await send_error(update)
        return E_ADD_CAT

async def get_expense_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query and update.callback_query.data == "exp_date_skip":
            await update.callback_query.answer()
            date_str = datetime.now().strftime("%d%m%Y")
            logger.info("get_expense_date: skipped, using today.")
        else:
            date_str = update.message.text.strip()
            try:
                datetime.strptime(date_str, "%d%m%Y")
                logger.info(f"get_expense_date: entered {date_str}")
            except Exception:
                logger.warning("get_expense_date: invalid format.")
                if update.message:
                    await update.message.reply_text("Format DDMMYYYY, please.")
                elif update.callback_query:
                    await update.callback_query.edit_message_text("Format DDMMYYYY, please.")
                return E_ADD_DATE
        context.user_data["exp_date"] = date_str

        d = context.user_data
        acct_label = d["exp_type"].capitalize()
        acct_id = d["exp_acct_id"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes", callback_data="exp_save_yes"),
             InlineKeyboardButton("❌ No",  callback_data="exp_save_no")]
        ])
        summary = (
            f"Account: {acct_label}\n"
            f"Account ID: {acct_id}\n"
            f"Amount: {fmt_money(d['exp_amt'], d['exp_cur'])}\n"
            f"Category: {d['exp_cat']}\n"
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
        if update.message:
            await update.message.reply_text("An error occurred. Please try again.")
        elif update.callback_query:
            await update.callback_query.edit_message_text("An error occurred. Please try again.")
        return ConversationHandler.END


@require_unlock
async def confirm_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.callback_query.answer()
        if update.callback_query.data != "exp_save_yes":
            logger.info("confirm_expense: user cancelled at confirmation.")
            await show_expense_menu(update, context)
            return ConversationHandler.END

        d = context.user_data
        record = {
            "account_type": d["exp_type"],
            "account_id": d["exp_acct_id"],
            "amount": d["exp_amt"],
            "currency": d["exp_cur"],
            "category": d.get("exp_cat", "General"),
            "note": d.get("exp_note", ""),
            "date": d["exp_date"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        logger.info(f"confirm_expense: saving expense record: {record}")
        expense_id = None
        try:
            expense_id = secure_db.insert("expenses", record)
            add_ledger_entry(
                account_type=d["exp_type"],
                account_id=d["exp_acct_id"],
                entry_type="expense",
                related_id=expense_id,
                amount=-abs(d["exp_amt"]),
                currency=d["exp_cur"],
                note=record.get("note", ""),
                date=d["exp_date"],
                timestamp=record["timestamp"],
            )
        except Exception as e:
            if expense_id is not None:
                secure_db.remove("expenses", [expense_id])
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
            f"[{r.doc_id}] {fmt_date(r.get('date',''))} {fmt_money(r['amount'], r['currency'])} | {r.get('category','')} | {r.get('note','')}"
            for r in chunk
        ]
        text = (f"🧾 Expenses  P{page}/"
                f"{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
                + "\n".join(lines))
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
        [InlineKeyboardButton("🔙 Back", callback_data="expense_menu")]
    ])
    await update.callback_query.edit_message_text("Edit expenses for which account type?", reply_markup=kb)
    return E_EDIT_TYPE

async def edit_get_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    t = update.callback_query.data.split("_")[-1]
    context.user_data["edit_type"] = t
    if t == "store":
        stores = secure_db.all("stores")
        if not stores:
            await update.callback_query.edit_message_text("No stores configured.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"exp_edit_acct_{s.doc_id}")]
            for s in stores
        ])
        await update.callback_query.edit_message_text("Select store:", reply_markup=kb)
        return E_EDIT_ACCT
    elif t == "partner":
        partners = secure_db.all("partners")
        if not partners:
            await update.callback_query.edit_message_text("No partners configured.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{p['name']} ({p['currency']})", callback_data=f"exp_edit_acct_{p.doc_id}")]
            for p in partners
        ])
        await update.callback_query.edit_message_text("Select partner:", reply_markup=kb)
        return E_EDIT_ACCT
    else:  # owner
        context.user_data["edit_acct_id"] = "POT"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Last 3 months", callback_data="exp_edit_time_3m")],
            [InlineKeyboardButton("Last 6 months", callback_data="exp_edit_time_6m")],
            [InlineKeyboardButton("All", callback_data="exp_edit_time_all")],
            [InlineKeyboardButton("🔙 Back", callback_data="edit_expense")]
        ])
        await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
        return E_EDIT_TIME

async def edit_get_acct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    acct_id = int(update.callback_query.data.split("_")[-1])
    context.user_data["edit_acct_id"] = acct_id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Last 3 months", callback_data="exp_edit_time_3m")],
        [InlineKeyboardButton("Last 6 months", callback_data="exp_edit_time_6m")],
        [InlineKeyboardButton("All", callback_data="exp_edit_time_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="edit_expense")]
    ])
    await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
    return E_EDIT_TIME

async def edit_get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
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
            f"[{r.doc_id}] {fmt_date(r.get('date',''))} {fmt_money(r['amount'], r['currency'])} | {r.get('category','')} | {r.get('note','')}"
            for r in chunk
        ]
        text = (f"✏️ Edit Expenses  P{page}/"
                f"{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
                + "\n".join(lines)
                + "\n\nSend DocID to edit:")
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="exp_edit_prev"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="exp_edit_next"))
    kb = InlineKeyboardMarkup([nav,
                               [InlineKeyboardButton("🔙 Back", callback_data="edit_expense")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return E_EDIT_PAGE

async def edit_paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_page"] += (
        -1 if update.callback_query.data.endswith("prev") else 1
    )
    return await render_edit_expense_page(update, context)

async def edit_pick_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        eid = int(update.message.text.strip())
        rec = secure_db.table("expenses").get(doc_id=eid)
        assert rec and rec["account_type"] == context.user_data["edit_type"] and str(rec["account_id"]) == str(context.user_data["edit_acct_id"])
    except Exception:
        await send_error(update, "❌ Invalid ID; try again:")
        return E_EDIT_PAGE
    context.user_data["edit_rec"] = rec
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Amount", callback_data="edit_field_amt")],
        [InlineKeyboardButton("Currency", callback_data="edit_field_cur")],
        [InlineKeyboardButton("Note", callback_data="edit_field_note")],
        [InlineKeyboardButton("Category", callback_data="edit_field_cat")],
        [InlineKeyboardButton("Date", callback_data="edit_field_date")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="edit_expense")],
    ])
    await update.message.reply_text("Editing expense. Choose field:", reply_markup=kb)
    return E_EDIT_FIELD

async def edit_choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    field = update.callback_query.data.split("_")[-1]
    context.user_data["edit_field"] = field
    if field == "amt":
        await update.callback_query.edit_message_text("New amount (positive number):")
    elif field == "cur":
        await update.callback_query.edit_message_text("New currency code (e.g. USD):")
    elif field == "note":
        await update.callback_query.edit_message_text("New note (or '-' to clear):")
    elif field == "cat":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(cat, callback_data=f"edit_cat_{cat.lower()}")] for cat in EXPENSE_CATS])
        await update.callback_query.edit_message_text("Select new category:", reply_markup=kb)
        return E_EDIT_NEWVAL
    elif field == "date":
        today = datetime.now().strftime("%d%m%Y")
        await update.callback_query.edit_message_text(f"New date DDMMYYYY (today {today}):")
    return E_EDIT_NEWVAL

async def edit_newval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data["edit_field"]
    if field == "cat":
        if update.callback_query:
            await update.callback_query.answer()
            val = update.callback_query.data.split("_")[-1].capitalize()
        else:
            val = update.message.text.strip().capitalize()
    else:
        val = update.message.text.strip()
    context.user_data["new_val"] = val
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="edit_exp_conf_yes"),
         InlineKeyboardButton("❌ No", callback_data="edit_exp_conf_no")]
    ])
    await update.message.reply_text(
        f"Change **{field}** to `{val}` ?",
        reply_markup=kb
    )
    return E_EDIT_CONFIRM

@require_unlock
async def edit_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if not update.callback_query.data.endswith("_yes"):
        await show_expense_menu(update, context)
        return ConversationHandler.END
    rec = context.user_data["edit_rec"]
    eid = rec.doc_id
    field = context.user_data["edit_field"]
    new = context.user_data["new_val"]

    update_dict = {}
    if field == "amt":
        try:
            amt = float(new)
            assert amt > 0
            update_dict["amount"] = amt
        except Exception:
            await send_error(update, "Invalid amount.")
            return ConversationHandler.END
    elif field == "cur":
        update_dict["currency"] = new.strip().upper()
    elif field == "note":
        update_dict["note"] = "" if new == "-" else new
    elif field == "cat":
        update_dict["category"] = new.capitalize()
    elif field == "date":
        try:
            datetime.strptime(new, "%d%m%Y")
            update_dict["date"] = new
        except Exception:
            await send_error(update, "Invalid date format.")
            return ConversationHandler.END

    try:
        secure_db.update("expenses", update_dict, [eid])
        # Remove previous ledger entry
        delete_ledger_entries_by_related(rec["account_type"], rec["account_id"], eid)
        # Re-insert to ledger
        rec = {**rec, **update_dict}
        add_ledger_entry(
            account_type=rec["account_type"],
            account_id=rec["account_id"],
            entry_type="expense",
            related_id=eid,
            amount=-abs(rec["amount"]),
            currency=rec["currency"],
            note=rec.get("note", ""),
            date=rec.get("date", ""),
            timestamp=rec.get("timestamp", ""),
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
            [InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"exp_del_acct_{s.doc_id}")]
            for s in stores
        ])
        await update.callback_query.edit_message_text("Select store:", reply_markup=kb)
        return E_DEL_ACCT
    elif t == "partner":
        partners = secure_db.all("partners")
        if not partners:
            await update.callback_query.edit_message_text("No partners configured.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{p['name']} ({p['currency']})", callback_data=f"exp_del_acct_{p.doc_id}")]
            for p in partners
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
            f"[{r.doc_id}] {fmt_date(r.get('date',''))} {fmt_money(r['amount'], r['currency'])} | {r.get('category','')} | {r.get('note','')}"
            for r in chunk
        ]
        text = (f"🗑️ Delete Expenses  P{page}/"
                f"{(total+ROWS_PER_PAGE-1)//ROWS_PER_PAGE}\n\n"
                + "\n".join(lines)
                + "\n\nSend DocID to delete:")
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
        eid = int(update.message.text.strip())
        rec = secure_db.table("expenses").get(doc_id=eid)
        assert rec and rec["account_type"] == context.user_data["del_type"] and str(rec["account_id"]) == str(context.user_data["del_acct_id"])
    except Exception:
        await send_error(update, "❌ Invalid ID; try again:")
        return E_DEL_PAGE
    context.user_data["del_rec"] = rec
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Delete", callback_data="del_exp_conf_yes"),
         InlineKeyboardButton("❌ Cancel", callback_data="del_exp_conf_no")]
    ])
    await update.message.reply_text(
        f"Delete expense [{eid}] {fmt_date(rec.get('date',''))} {fmt_money(rec['amount'], rec['currency'])}?",
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
    eid = rec.doc_id
    try:
        secure_db.remove("expenses", [eid])
        delete_ledger_entries_by_related(rec["account_type"], rec["account_id"], eid)
    except Exception as e:
        logger.error(f"Failed to delete expense: {e}")
        await send_error(update, "❌ Error deleting expense.")
        return ConversationHandler.END

    await update.callback_query.edit_message_text("✅ Expense deleted.")
    return ConversationHandler.END


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
            E_ADD_NOTE:   [
                CallbackQueryHandler(get_expense_note, pattern="^exp_note_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_expense_note),
            ],
            E_ADD_CAT:    [CallbackQueryHandler(get_expense_cat, pattern="^exp_cat_")],
            E_ADD_DATE:   [
                CallbackQueryHandler(get_expense_date, pattern="^exp_date_skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_expense_date),
            ],
            E_ADD_CONFIRM:[CallbackQueryHandler(confirm_expense, pattern="^exp_save_")],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    app.add_handler(add_conv)

    # --- View Flow ---
    view_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(view_expense_start, pattern="^view_expense$"),
        ],
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
            E_EDIT_NEWVAL: [
                CallbackQueryHandler(edit_newval, pattern="^edit_cat_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_newval)
            ],
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

