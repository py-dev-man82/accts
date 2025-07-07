# handlers/reports/customer_report.py

from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from secure_db import secure_db
from handlers.utils import require_unlock, format_currency, format_date

# ────────────────────────────────────────────────────────────
#  Conversation-state constants
# ────────────────────────────────────────────────────────────
(
    CUST_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_DISPLAY,
) = range(5)


# ────────────────────────────────────────────────────────────
#  Menu
# ────────────────────────────────────────────────────────────
async def show_customer_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show customer report menu"""
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers found.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
            ),
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"custrep_{c.doc_id}")
        for c in customers
    ]
    grid = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    grid.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])

    await update.callback_query.edit_message_text(
        "📄 Select a customer to view report:", reply_markup=InlineKeyboardMarkup(grid)
    )
    return CUST_SELECT


# ────────────────────────────────────────────────────────────
#  Date Range Selection
# ────────────────────────────────────────────────────────────
async def select_date_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data["customer_id"] = cid

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Weekly (Last 7 days)", callback_data="daterange_weekly")],
        [InlineKeyboardButton("📆 Custom Range", callback_data="daterange_custom")],
        [InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu")],
    ])
    await update.callback_query.edit_message_text("Choose date range:", reply_markup=kb)
    return DATE_RANGE_SELECT


async def get_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📅 Enter start date (DDMMYYYY):"
    )
    return CUSTOM_DATE_INPUT


async def save_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        start_date = datetime.strptime(text, "%d%m%Y")
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Enter date as DDMMYYYY.")
        return CUSTOM_DATE_INPUT

    context.user_data["start_date"] = start_date
    context.user_data["end_date"] = datetime.now()
    return await choose_report_scope(update, context)


# ────────────────────────────────────────────────────────────
#  Scope Selection
# ────────────────────────────────────────────────────────────
async def choose_report_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.data == "daterange_weekly":
            context.user_data["start_date"] = datetime.now() - timedelta(days=7)
            context.user_data["end_date"] = datetime.now()
        elif update.callback_query.data == "daterange_custom":
            return await get_custom_date(update, context)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Full Report", callback_data="scope_full")],
        [InlineKeyboardButton("🛒 Sales Only", callback_data="scope_sales")],
        [InlineKeyboardButton("💵 Payments Only", callback_data="scope_payments")],
        [InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu")],
    ])
    await update.callback_query.edit_message_text("Choose report scope:", reply_markup=kb)
    return REPORT_SCOPE_SELECT


# ────────────────────────────────────────────────────────────
#  Report Display
# ────────────────────────────────────────────────────────────
async def show_customer_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    scope = update.callback_query.data.split("_")[-1]
    context.user_data["scope"] = scope

    cid = context.user_data["customer_id"]
    start_date = context.user_data["start_date"]
    end_date = context.user_data["end_date"]
    customer = secure_db.table("customers").get(doc_id=cid)

    # Fetch data
    sales = [
        s for s in secure_db.all("sales")
        if s["customer_id"] == cid and start_date <= datetime.fromisoformat(s["timestamp"]) <= end_date
    ]
    payments = [
        p for p in secure_db.all("customer_payments")
        if p["customer_id"] == cid and start_date <= datetime.fromisoformat(p["timestamp"]) <= end_date
    ]

    # Calculate totals
    total_sales = sum(s["quantity"] * s["unit_price"] for s in sales)
    total_payments = sum(p["local_amt"] for p in payments)
    balance = total_sales - total_payments

    # Format report
    report_lines = [f"📄 **Customer Report: {customer['name']}**"]
    report_lines.append(f"Period: {format_date(start_date)} → {format_date(end_date)}")
    report_lines.append(f"Currency: {customer['currency']}\n")

    if scope in ["full", "sales"]:
        report_lines.append("🛒 **Sales**")
        if sales:
            for s in sales:
                report_lines.append(
                    f"• {format_date(datetime.fromisoformat(s['timestamp']))}: "
                    f"Item {s['item_id']} x{s['quantity']} @ {format_currency(s['unit_price'], customer['currency'])} "
                    f"= {format_currency(s['quantity'] * s['unit_price'], customer['currency'])}"
                )
        else:
            report_lines.append("  (No sales)")

    if scope in ["full", "payments"]:
        report_lines.append("\n💵 **Payments**")
        if payments:
            for p in payments:
                report_lines.append(
                    f"• {format_date(datetime.fromisoformat(p['timestamp']))}: "
                    f"{format_currency(p['local_amt'], customer['currency'])} "
                    f"(Fee: {format_currency(p['fee_amt'], customer['currency'])}) → "
                    f"{format_currency(p['usd_amt'], 'USD')} @ {p['fx_rate']:.4f}"
                )
        else:
            report_lines.append("  (No payments)")

    report_lines.append(f"\n📊 **Balance:** {format_currency(balance, customer['currency'])}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu")]
    ])
    await update.callback_query.edit_message_text("\n".join(report_lines), reply_markup=kb)
    return ConversationHandler.END


# ────────────────────────────────────────────────────────────
#  Register Handlers
# ────────────────────────────────────────────────────────────
def register_customer_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$"))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_customer_report_menu, pattern="^rep_cust$")],
        states={
            CUST_SELECT:        [CallbackQueryHandler(select_date_range, pattern="^custrep_")],
            DATE_RANGE_SELECT:  [CallbackQueryHandler(choose_report_scope, pattern="^daterange_")],
            CUSTOM_DATE_INPUT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_date)],
            REPORT_SCOPE_SELECT:[CallbackQueryHandler(show_customer_report, pattern="^scope_")],
        },
        fallbacks=[CommandHandler("cancel", show_customer_report_menu)],
        per_message=False,
    )
    app.add_handler(conv)