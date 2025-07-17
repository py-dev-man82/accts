# handlers/dividends.py

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
from secure_db import secure_db
from handlers.utils import require_unlock_and_admin, fmt_money, fmt_date
from handlers.ledger import add_ledger_entry, delete_ledger_entries_by_related

logger = logging.getLogger("dividends")
DEBUG_HANDLERS = True
TRACE_HANDLERS = True
STRICT_VALIDATION = True  # ✅ Toggle strict input validation

def log_debug(msg):
    if DEBUG_HANDLERS:
        logger.debug(msg)

def log_trace(msg):
    if TRACE_HANDLERS:
        logger.debug(f"[TRACE] {msg}")

# ✅ Catch-all for stray inputs
async def invalid_numeric_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f"Invalid numeric input: {update.message.text}")
    await update.message.reply_text("❌ Please enter a valid number.")
    return ConversationHandler.END

async def invalid_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f"Invalid date input: {update.message.text}")
    await update.message.reply_text("❌ Please enter a date in DDMMYYYY format.")
    return ConversationHandler.END

async def trace_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f"[TRACE] Unhandled message: {update.message.text}")
    await update.message.reply_text("⚠️ Debug: Message received but no handler matched.")
    return ConversationHandler.END

(
    DIV_DEBIT_PROJECT_SELECT,
    DIV_CREDIT_PROJECT_SELECT,
    DIV_CREDIT_AMOUNT,
    DIV_CREDIT_CONFIRM,
    DIV_WITHDRAW_PROJECT,
    DIV_WITHDRAW_LOCAL,
    DIV_WITHDRAW_FEE,
    DIV_WITHDRAW_USD,
    DIV_WITHDRAW_CONFIRM,
    DIV_EXPENSE_PROJECT_SELECT,
    DIV_EXPENSE_DEBIT_PROJECT_SELECT,
    DIV_EXPENSE_LOCAL_PAID,
    DIV_EXPENSE_LOCAL_RECEIVED,
    DIV_EXPENSE_FEE,
    DIV_EXPENSE_DESC,
    DIV_EXPENSE_CONFIRM,
    DIV_EDIT_TYPE,
    DIV_EDIT_PROJECT,
    DIV_EDIT_SELECT,
    DIV_EDIT_FIELD,
    DIV_EDIT_NEWVAL,
    DIV_EDIT_CONFIRM,
    DIV_REPORT_PROJECT,
    DIV_REPORT_DATE,
) = range(24)

OWNER_ACCOUNT_ID = "POT"
# ===================== MAIN MENU =====================
@require_unlock_and_admin
async def dividends_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    log_debug("dividends_menu called")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Credit Dividends", callback_data="div_credit")],
        [InlineKeyboardButton("📤 Withdraw Dividends", callback_data="div_withdraw")],
        [InlineKeyboardButton("🧾 Pay Project Expenses", callback_data="div_expense")],
        [InlineKeyboardButton("✏️ Edit / Delete", callback_data="edit_delete")],
        [InlineKeyboardButton("📊 View Report", callback_data="view_report")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(
            "Welcome to the Dividends Management. Choose an action:", reply_markup=kb)
    else:
        await update.message.reply_text(
            "Welcome to the Dividends Management. Choose an action:", reply_markup=kb)
    return ConversationHandler.END

@require_unlock_and_admin
async def handle_dividends_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    log_trace(f"Dividends menu callback: {data}")
    if data == "div_credit":
        return await start_credit_dividends(update, context)
    elif data == "div_withdraw":
        return await start_withdraw_dividends(update, context)
    elif data == "div_expense":
        return await start_project_expense(update, context)
    elif data == "edit_delete":
        return await start_edit_delete(update, context)
    elif data == "view_report":
        return await start_view_report(update, context)
    elif data == "dividends_menu":
        return await dividends_menu(update, context)
    else:
        await update.callback_query.answer("Unknown option.")
        return ConversationHandler.END
# ===================== CREDIT DIVIDENDS FLOW =====================
@require_unlock_and_admin
async def start_credit_dividends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    projects = secure_db.table("partners").all()
    kb = [
        [InlineKeyboardButton(p['name'], callback_data=f"credit_debit_project_{p.doc_id}")] for p in projects
    ]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")])
    await update.callback_query.edit_message_text("Select Project to debit:", reply_markup=InlineKeyboardMarkup(kb))
    return DIV_DEBIT_PROJECT_SELECT

@require_unlock_and_admin
async def credit_select_debit_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = int(update.callback_query.data.replace("credit_debit_project_", ""))
    context.user_data["debit_project_id"] = project_id
    projects = secure_db.table("partners").all()
    kb = [
        [InlineKeyboardButton(p['name'], callback_data=f"credit_credit_project_{p.doc_id}")] for p in projects
    ]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")])
    await update.callback_query.edit_message_text("Select Partner to credit:", reply_markup=InlineKeyboardMarkup(kb))
    return DIV_CREDIT_PROJECT_SELECT

@require_unlock_and_admin
async def credit_select_credit_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    credit_project_id = int(update.callback_query.data.replace("credit_credit_project_", ""))
    context.user_data["credit_project_id"] = credit_project_id
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.callback_query.edit_message_text("Enter amount to credit:", reply_markup=kb)
    return DIV_CREDIT_AMOUNT

@require_unlock_and_admin
async def credit_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
    except ValueError:
        return await invalid_numeric_input(update, context)

    context.user_data["credit_amount"] = amount
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="credit_confirm")],
        [InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]
    ])
    await update.message.reply_text(
        f"Transfer {fmt_money(amount)} from selected debit Project to selected credit Project. Confirm?",
        reply_markup=kb
    )
    return DIV_CREDIT_CONFIRM

@require_unlock_and_admin
async def credit_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debit_project_id = context.user_data["debit_project_id"]
    credit_project_id = context.user_data["credit_project_id"]
    amount = context.user_data["credit_amount"]
    project = secure_db.table("partners").get(doc_id=credit_project_id)
    currency = project["currency"]
    timestamp = datetime.utcnow().isoformat()
    related_id = None
    try:
        related_id = add_ledger_entry(
            account_type="partner",
            account_id=debit_project_id,
            entry_type="project_payout",
            related_id=None,
            amount=-amount,
            currency=currency,
            note="Dividends paid to partner",
            timestamp=timestamp
        )
        add_ledger_entry(
            account_type="partner_dividends",
            account_id=credit_project_id,
            entry_type="dividend_credit",
            related_id=related_id,
            amount=amount,
            currency=currency,
            note="Dividends credited from project",
            timestamp=timestamp
        )
        secure_db.insert("project_dividends", {
            "debit_project_id": debit_project_id,
            "credit_project_id": credit_project_id,
            "amount": amount,
            "currency": currency,
            "timestamp": timestamp,
            "related_id": related_id
        })
        await update.callback_query.edit_message_text(f"✅ Credited {fmt_money(amount, currency)} to selected project.")
    except Exception as e:
        logger.error(f"Error in credit_confirm: {e}")
        if related_id:
            delete_ledger_entries_by_related("partner", debit_project_id, related_id)
        await update.callback_query.edit_message_text("❌ Failed to credit dividends. Rolled back.")
    return ConversationHandler.END
# ===================== WITHDRAW DIVIDENDS FLOW =====================
@require_unlock_and_admin
async def start_withdraw_dividends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    projects = secure_db.table("partners").all()
    kb = [
        [InlineKeyboardButton(p['name'], callback_data=f"withdraw_project_{p.doc_id}")]
        for p in projects
    ]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")])
    await update.callback_query.edit_message_text("Select Project to withdraw from:", reply_markup=InlineKeyboardMarkup(kb))
    return DIV_WITHDRAW_PROJECT

@require_unlock_and_admin
async def withdraw_select_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = int(update.callback_query.data.replace("withdraw_project_", ""))
    context.user_data["project_id"] = project_id
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.callback_query.edit_message_text("Enter local currency amount to withdraw:", reply_markup=kb)
    return DIV_WITHDRAW_LOCAL

@require_unlock_and_admin
async def withdraw_local_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
    except ValueError:
        return await invalid_numeric_input(update, context)

    context.user_data["withdraw_local"] = amount
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.message.reply_text("Enter handling fee (enter 0 if none):", reply_markup=kb)
    return DIV_WITHDRAW_FEE

@require_unlock_and_admin
async def withdraw_fee_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee = float(update.message.text)
    except ValueError:
        return await invalid_numeric_input(update, context)

    context.user_data["withdraw_fee"] = fee
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.message.reply_text("Enter USD amount paid to the partner:", reply_markup=kb)
    return DIV_WITHDRAW_USD

@require_unlock_and_admin
async def withdraw_usd_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd_amount = float(update.message.text)
    except ValueError:
        return await invalid_numeric_input(update, context)

    local = context.user_data["withdraw_local"]
    fee = context.user_data["withdraw_fee"]
    fx_rate = (local - fee) / usd_amount if usd_amount else 0
    context.user_data["withdraw_usd"] = usd_amount
    context.user_data["withdraw_fx"] = fx_rate
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="withdraw_confirm")],
        [InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]
    ])
    await update.message.reply_text(
        f"Withdraw {fmt_money(local)} (fee {fmt_money(fee)}), USD paid {usd_amount}, FX rate {fx_rate:.4f}\nConfirm?",
        reply_markup=kb
    )
    return DIV_WITHDRAW_CONFIRM

@require_unlock_and_admin
async def withdraw_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = context.user_data["project_id"]
    amount = context.user_data["withdraw_local"]
    fee = context.user_data["withdraw_fee"]
    usd_amount = context.user_data["withdraw_usd"]
    fx_rate = context.user_data["withdraw_fx"]
    project = secure_db.table("partners").get(doc_id=project_id)
    currency = project["currency"]
    timestamp = datetime.utcnow().isoformat()
    related_id = None
    try:
        related_id = add_ledger_entry(
            account_type="partner_dividends",
            account_id=project_id,
            entry_type="dividend_withdrawal",
            related_id=None,
            amount=-amount,
            currency=currency,
            note="Dividends withdrawal",
            timestamp=timestamp
        )
        add_ledger_entry(
            account_type="owner",
            account_id=OWNER_ACCOUNT_ID,
            entry_type="payout_sent",
            related_id=related_id,
            amount=-usd_amount,
            currency="USD",
            fx_rate=fx_rate,
            fee_amt=fee,
            usd_amt=usd_amount,
            note="USD paid for dividends withdrawal",
            timestamp=timestamp
        )
        if fee > 0:
            add_ledger_entry(
                account_type="owner",
                account_id=OWNER_ACCOUNT_ID,
                entry_type="fee",
                related_id=related_id,
                amount=fee,
                currency=currency,
                note="Handling fee for dividends withdrawal",
                timestamp=timestamp
            )
        secure_db.insert("project_dividends_withdrawals", {
            "project_id": project_id,
            "local_amount": amount,
            "currency": currency,
            "usd_amount": usd_amount,
            "fx_rate": fx_rate,
            "fee": fee,
            "timestamp": timestamp,
            "related_id": related_id
        })
        await update.callback_query.edit_message_text(f"✅ Withdrawal of {fmt_money(amount, currency)} recorded.")
    except Exception as e:
        logger.error(f"Error in withdraw_confirm: {e}")
        if related_id:
            delete_ledger_entries_by_related("partner_dividends", project_id, related_id)
        await update.callback_query.edit_message_text("❌ Failed to record withdrawal. Rolled back.")
    return ConversationHandler.END
# ===================== PAY PROJECT EXPENSES FLOW =====================
@require_unlock_and_admin
async def start_project_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    projects = secure_db.table("partners").all()
    kb = [
        [InlineKeyboardButton(p['name'], callback_data=f"expense_credit_project_{p.doc_id}")]
        for p in projects
    ]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")])
    await update.callback_query.edit_message_text("Select Project to receive funds:", reply_markup=InlineKeyboardMarkup(kb))
    return DIV_EXPENSE_PROJECT_SELECT

@require_unlock_and_admin
async def expense_select_credit_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    credit_project_id = int(update.callback_query.data.replace("expense_credit_project_", ""))
    context.user_data["credit_project_id"] = credit_project_id
    projects = secure_db.table("partners").all()
    kb = [
        [InlineKeyboardButton(p['name'], callback_data=f"expense_debit_project_{p.doc_id}")]
        for p in projects
    ]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")])
    await update.callback_query.edit_message_text("Select Project to debit funds from:", reply_markup=InlineKeyboardMarkup(kb))
    return DIV_EXPENSE_DEBIT_PROJECT_SELECT

@require_unlock_and_admin
async def expense_select_debit_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debit_project_id = int(update.callback_query.data.replace("expense_debit_project_", ""))
    context.user_data["debit_project_id"] = debit_project_id
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.callback_query.edit_message_text("Enter local amount paid (debited project currency):", reply_markup=kb)
    return DIV_EXPENSE_LOCAL_PAID

@require_unlock_and_admin
async def expense_local_paid_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        local_paid = float(update.message.text)
    except ValueError:
        return await invalid_numeric_input(update, context)

    context.user_data["local_paid"] = local_paid
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.message.reply_text("Enter local amount received (credited project currency):", reply_markup=kb)
    return DIV_EXPENSE_LOCAL_RECEIVED

@require_unlock_and_admin
async def expense_local_received_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        local_received = float(update.message.text)
    except ValueError:
        return await invalid_numeric_input(update, context)

    context.user_data["local_received"] = local_received
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.message.reply_text("Enter handling fee (enter 0 if none):", reply_markup=kb)
    return DIV_EXPENSE_FEE

@require_unlock_and_admin
async def expense_fee_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fee = float(update.message.text)
    except ValueError:
        return await invalid_numeric_input(update, context)

    context.user_data["fee"] = fee
    local_paid = context.user_data["local_paid"]
    local_received = context.user_data["local_received"]
    fx_rate = (local_paid - fee) / local_received if local_received else 0
    context.user_data["fx_rate"] = fx_rate
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.message.reply_text("Enter description for expense:", reply_markup=kb)
    return DIV_EXPENSE_DESC

@require_unlock_and_admin
async def expense_desc_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    context.user_data["expense_desc"] = desc
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="expense_confirm")],
        [InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]
    ])
    await update.message.reply_text(
        f"Confirm expense:\n"
        f"- From: Debited Project\n"
        f"- To: Credited Project\n"
        f"- Amount Paid: {fmt_money(context.user_data['local_paid'])}\n"
        f"- Amount Received: {fmt_money(context.user_data['local_received'])}\n"
        f"- Fee: {fmt_money(context.user_data['fee'])}\n"
        f"- FX Rate: {context.user_data['fx_rate']:.4f}\n"
        f"- Description: {desc}",
        reply_markup=kb
    )
    return DIV_EXPENSE_CONFIRM

@require_unlock_and_admin
async def expense_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debit_project_id = context.user_data["debit_project_id"]
    credit_project_id = context.user_data["credit_project_id"]
    local_paid = context.user_data["local_paid"]
    local_received = context.user_data["local_received"]
    fee = context.user_data["fee"]
    fx_rate = context.user_data["fx_rate"]
    desc = context.user_data["expense_desc"]
    debit_project = secure_db.table("partners").get(doc_id=debit_project_id)
    credit_project = secure_db.table("partners").get(doc_id=credit_project_id)
    debit_currency = debit_project["currency"]
    credit_currency = credit_project["currency"]
    timestamp = datetime.utcnow().isoformat()
    related_id = None
    try:
        related_id = add_ledger_entry(
            account_type="partner",
            account_id=debit_project_id,
            entry_type="investor_expense",
            related_id=None,
            amount=-local_paid,
            currency=debit_currency,
            fx_rate=fx_rate,
            fee_amt=fee,
            note=desc,
            timestamp=timestamp
        )
        add_ledger_entry(
            account_type="partner",
            account_id=credit_project_id,
            entry_type="expense_credit",
            related_id=related_id,
            amount=local_received,
            currency=credit_currency,
            fx_rate=fx_rate,
            note=desc,
            timestamp=timestamp
        )
        if fee > 0:
            add_ledger_entry(
                account_type="owner",
                account_id=OWNER_ACCOUNT_ID,
                entry_type="fee",
                related_id=related_id,
                amount=fee,
                currency=debit_currency,
                note="Handling fee for project expense",
                timestamp=timestamp
            )
        secure_db.insert("project_expense_payments", {
            "debit_project_id": debit_project_id,
            "credit_project_id": credit_project_id,
            "local_paid": local_paid,
            "local_received": local_received,
            "fee": fee,
            "fx_rate": fx_rate,
            "currency_paid": debit_currency,
            "currency_received": credit_currency,
            "description": desc,
            "timestamp": timestamp,
            "related_id": related_id
        })
        await update.callback_query.edit_message_text(f"✅ Project expense of {fmt_money(local_paid, debit_currency)} recorded.")
    except Exception as e:
        logger.error(f"Error in expense_confirm: {e}")
        if related_id:
            delete_ledger_entries_by_related("partner", debit_project_id, related_id)
        await update.callback_query.edit_message_text("❌ Failed to record project expense. Rolled back.")
    return ConversationHandler.END
# ===================== REPORT FLOW (LEDGER-BASED) =====================
@require_unlock_and_admin
async def start_view_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    projects = secure_db.table("partners").all()
    kb = [
        [InlineKeyboardButton(p['name'], callback_data=f"report_project_{p.doc_id}")]
        for p in projects
    ]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")])
    await update.callback_query.edit_message_text("Select Project to view report:", reply_markup=InlineKeyboardMarkup(kb))
    return DIV_REPORT_PROJECT

@require_unlock_and_admin
async def report_select_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = int(update.callback_query.data.replace("report_project_", ""))
    context.user_data["project_id"] = project_id
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.callback_query.edit_message_text("Enter report start date (DDMMYYYY):", reply_markup=kb)
    return DIV_REPORT_DATE

@require_unlock_and_admin
async def report_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["report_start"] = update.message.text.strip()
    return await send_project_report(update, context)

@require_unlock_and_admin
async def send_project_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = context.user_data["project_id"]
    start_date = context.user_data["report_start"]
    end_date = datetime.utcnow().strftime("%d%m%Y")
    ledger_entries = secure_db.table("ledger").search(
        lambda x: (
            x["account_id"] == project_id and
            start_date <= x["timestamp"] <= end_date
        )
    )

    lines = ["📊 Report", f"Period: {fmt_date(start_date)} → {fmt_date(end_date)}", ""]

    # Transfers In
    lines.append("─────────────────────────────")
    lines.append("📥 Transfers In:")
    for entry in ledger_entries:
        if entry["entry_type"] == "dividend_credit":
            lines.append(f"• {fmt_date(entry['timestamp'])}  +{fmt_money(entry['amount'], entry['currency'])} {entry['note']}")

    # Withdrawals
    lines.append("─────────────────────────────")
    lines.append("📤 Withdrawals:")
    for entry in ledger_entries:
        if entry["entry_type"] == "dividend_withdrawal":
            lines.append(f"• {fmt_date(entry['timestamp'])}  -{fmt_money(entry['amount'], entry['currency'])} → USD {entry.get('usd_amt', 0)} @ FX {entry.get('fx_rate', 0):.4f}")

    # Expenses Paid
    lines.append("─────────────────────────────")
    lines.append("🧾 Expenses Paid:")
    for entry in ledger_entries:
        if entry["entry_type"] == "investor_expense":
            lines.append(f"• {fmt_date(entry['timestamp'])}  -{fmt_money(entry['amount'], entry['currency'])} {entry['note']}")

    # Fees
    lines.append("─────────────────────────────")
    lines.append("💸 Fees:")
    for entry in ledger_entries:
        if entry["entry_type"] == "fee":
            lines.append(f"• {fmt_date(entry['timestamp'])}  -{fmt_money(entry['amount'], entry['currency'])} {entry['note']}")

    lines.append("─────────────────────────────")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]])
    await update.message.reply_text("\n".join(lines), reply_markup=kb)
    return ConversationHandler.END

# ===================== EDIT/DELETE FLOW =====================
@require_unlock_and_admin
async def start_edit_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Dividends Credits", callback_data="edit_credits")],
        [InlineKeyboardButton("📤 Withdrawals", callback_data="edit_withdrawals")],
        [InlineKeyboardButton("🧾 Project Expenses", callback_data="edit_expenses")],
        [InlineKeyboardButton("🔙 Back", callback_data="dividends_menu")]
    ])
    await update.callback_query.edit_message_text("Select what to edit or delete:", reply_markup=kb)
    return DIV_EDIT_TYPE

@require_unlock_and_admin
async def edit_select_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["edit_type"] = update.callback_query.data
    projects = secure_db.table("partners").all()
    kb = [
        [InlineKeyboardButton(p['name'], callback_data=f"edit_project_{p.doc_id}")]
        for p in projects
    ]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="start_edit_delete")])
    await update.callback_query.edit_message_text("Select Project:", reply_markup=InlineKeyboardMarkup(kb))
    return DIV_EDIT_PROJECT

@require_unlock_and_admin
async def edit_select_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = int(update.callback_query.data.replace("edit_project_", ""))
    context.user_data["project_id"] = project_id
    edit_type = context.user_data["edit_type"]

    # Fetch records based on edit type
    if edit_type == "edit_credits":
        table_name = "project_dividends"
        records = secure_db.table(table_name).search(lambda x: x["credit_project_id"] == project_id)
    elif edit_type == "edit_withdrawals":
        table_name = "project_dividends_withdrawals"
        records = secure_db.table(table_name).search(lambda x: x["project_id"] == project_id)
    elif edit_type == "edit_expenses":
        table_name = "project_expense_payments"
        records = secure_db.table(table_name).search(lambda x: x["credit_project_id"] == project_id)

    context.user_data["table_name"] = table_name

    if not records:
        await update.callback_query.edit_message_text("No records found for this project.")
        return ConversationHandler.END

    kb = [
        [InlineKeyboardButton(
            f"{fmt_date(r['timestamp'])} - {fmt_money(r.get('amount', r.get('local_amount')), r['currency'])}",
            callback_data=f"edit_record_{r['related_id']}"
        )]
        for r in records
    ]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="start_edit_delete")])
    await update.callback_query.edit_message_text("Select a record:", reply_markup=InlineKeyboardMarkup(kb))
    return DIV_EDIT_SELECT

@require_unlock_and_admin
async def edit_record_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    related_id = update.callback_query.data.replace("edit_record_", "")
    context.user_data["related_id"] = related_id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit Record", callback_data="edit_record"),
         InlineKeyboardButton("🗑 Delete Record", callback_data="delete_record")],
        [InlineKeyboardButton("🔙 Back", callback_data="start_edit_delete")]
    ])
    await update.callback_query.edit_message_text("Choose an action for this record:", reply_markup=kb)
    return DIV_EDIT_FIELD

@require_unlock_and_admin
async def edit_field_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Amount", callback_data="field_amount")],
        [InlineKeyboardButton("💸 Fee", callback_data="field_fee")],
        [InlineKeyboardButton("📈 FX Rate", callback_data="field_fx")],
        [InlineKeyboardButton("📝 Description", callback_data="field_note")],
        [InlineKeyboardButton("🔙 Back", callback_data="edit_record_action")]
    ])
    await update.callback_query.edit_message_text("Select a field to edit:", reply_markup=kb)
    return DIV_EDIT_FIELD

@require_unlock_and_admin
async def edit_choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field_map = {
        "field_amount": "amount",
        "field_fee": "fee",
        "field_fx": "fx_rate",
        "field_note": "description",
    }
    field = field_map.get(update.callback_query.data)
    if not field:
        await update.callback_query.answer("Unknown field.")
        return DIV_EDIT_FIELD

    context.user_data["edit_field"] = field
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="edit_field_selection")]])
    await update.callback_query.edit_message_text(f"Enter new value for {field.replace('_', ' ').title()}:", reply_markup=kb)
    return DIV_EDIT_NEWVAL

@require_unlock_and_admin
async def edit_new_value_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_value"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Edit", callback_data="edit_confirm")],
        [InlineKeyboardButton("🔙 Back", callback_data="edit_field_selection")]
    ])
    await update.message.reply_text(f"Confirm new value: {context.user_data['new_value']}", reply_markup=kb)
    return DIV_EDIT_CONFIRM

@require_unlock_and_admin
async def edit_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = context.user_data["project_id"]
    related_id = context.user_data["related_id"]
    table_name = context.user_data["table_name"]
    field = context.user_data["edit_field"]
    new_value = context.user_data["new_value"]

    try:
        # Rollback old ledger entries
        delete_ledger_entries_by_related("partner", project_id, related_id)

        # Fetch DB record
        record = secure_db.table(table_name).get(lambda x: x["related_id"] == related_id)

        # Update record
        record[field] = float(new_value) if field in ["amount", "fee", "fx_rate"] else new_value
        secure_db.update(table_name, lambda x: x["related_id"] == related_id, record)

        await update.callback_query.edit_message_text("✅ Record updated successfully.")
    except Exception as e:
        logger.error(f"Error updating record: {e}")
        await update.callback_query.edit_message_text("❌ Failed to update record.")
    return ConversationHandler.END

@require_unlock_and_admin
async def confirm_delete_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_id = context.user_data["project_id"]
    related_id = context.user_data["related_id"]
    table_name = context.user_data["table_name"]

    try:
        secure_db.remove(table_name, lambda r: r["related_id"] == related_id)
        delete_ledger_entries_by_related("partner", project_id, related_id)
        await update.callback_query.edit_message_text("✅ Record deleted successfully.")
    except Exception as e:
        logger.error(f"Error deleting record: {e}")
        await update.callback_query.edit_message_text("❌ Failed to delete record.")
    return ConversationHandler.END


# ===================== DEBUG FALLBACK =====================
async def invalid_numeric_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f"[WARN] Invalid numeric input: {update.message.text}")
    await update.message.reply_text("❌ Invalid input. Please enter a valid number.")
    return ConversationHandler.END

async def trace_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.debug(f"[TRACE] Unhandled message: {update.message.text}")
    await update.message.reply_text("⚠️ Debug: Message received but no handler matched.")
    return ConversationHandler.END

# ===================== END OF DIVIDENDS MODULE =====================
