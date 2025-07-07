# handlers/reports/customer_report.py

import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from secure_db import secure_db
from handlers.utils import require_unlock, fmt_money, fmt_date

# Conversation states
(
    CUST_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_PAGE,
) = range(5)

# Number of items per page
_PAGE_SIZE = 8

@require_unlock
async def show_customer_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("show_customer_report_menu called")
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "⚠️ No customers found.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu")]
            ])
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"custrep_{c.doc_id}")
        for c in customers
    ]
    grid = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    grid.append([InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu")])

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📄 Select a customer to view report:",
        reply_markup=InlineKeyboardMarkup(grid)
    )
    return CUST_SELECT

async def select_date_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("select_date_range: %s", update.callback_query.data)
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data["customer_id"] = cid

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Weekly (Last 7 days)", callback_data="daterange_weekly")],
        [InlineKeyboardButton("📆 Custom Range", callback_data="daterange_custom")],
        [InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu")],
    ])
    await update.callback_query.edit_message_text(
        "Choose date range:", reply_markup=kb
    )
    return DATE_RANGE_SELECT

async def get_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_custom_date")
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("📅 Enter start date (DDMMYYYY):")
    return CUSTOM_DATE_INPUT

async def save_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("save_custom_date: %s", update.message.text)
    text = update.message.text.strip()
    try:
        start_date = datetime.strptime(text, "%d%m%Y")
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Enter date as DDMMYYYY.")
        return CUSTOM_DATE_INPUT

    context.user_data["start_date"] = start_date
    context.user_data["end_date"] = datetime.now()
    return await choose_report_scope(update, context)

async def choose_report_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("choose_report_scope: %s", update.callback_query.data)
    await update.callback_query.answer()
    data = update.callback_query.data
    if data == "daterange_weekly":
        context.user_data["start_date"] = datetime.now() - timedelta(days=7)
        context.user_data["end_date"] = datetime.now()
    elif data == "daterange_custom":
        return await get_custom_date(update, context)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Full Report", callback_data="scope_full")],
        [InlineKeyboardButton("🛒 Sales Only", callback_data="scope_sales")],
        [InlineKeyboardButton("💵 Payments Only", callback_data="scope_payments")],
        [InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu")],
    ])
    await update.callback_query.edit_message_text("Choose report scope:", reply_markup=kb)
    return REPORT_SCOPE_SELECT

# Helper for pagination
def _paginate(items, page):
    start = page * _PAGE_SIZE
    return items[start:start + _PAGE_SIZE], len(items)

@require_unlock
async def show_customer_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("show_customer_report: page=%s scope=%s", context.user_data.get("page"), context.user_data.get("scope"))
    await update.callback_query.answer()
    scope = update.callback_query.data.split("_")[-1]
    context.user_data["scope"] = scope
    context.user_data.setdefault("page", 0)

    cid = context.user_data["customer_id"]
    start_date = context.user_data["start_date"]
    end_date = context.user_data["end_date"]
    page = context.user_data["page"]
    customer = secure_db.table("customers").get(doc_id=cid)

    all_sales = [
        s for s in secure_db.all("sales")
        if s["customer_id"] == cid and start_date <= datetime.fromisoformat(s["timestamp"]) <= end_date
    ]
    all_payments = [
        p for p in secure_db.all("customer_payments")
        if p["customer_id"] == cid and start_date <= datetime.fromisoformat(p["timestamp"]) <= end_date
    ]

    total_sales = sum(s["quantity"] * s["unit_price"] for s in all_sales)
    total_payments_local = sum(p["local_amt"] for p in all_payments)
    total_payments_usd = sum(p["usd_amt"] for p in all_payments)
    balance = total_sales - total_payments_local

    sales_page, sales_count = _paginate(all_sales, page) if scope in ["full", "sales"] else ([], 0)
    payments_page, payments_count = _paginate(all_payments, page) if scope in ["full", "payments"] else ([], 0)

    lines = [
        f"📄 *Customer Report: {customer['name']}*",
        f"Period: {fmt_date(start_date.strftime('%d%m%Y'))} → {fmt_date(end_date.strftime('%d%m%Y'))}",
        f"Currency: {customer['currency']}\n"
    ]

    if scope in ["full", "sales"]:
        lines.append("🛒 *Sales*")
        if sales_page:
            for s in sales_page:
                date = datetime.fromisoformat(s['timestamp']).strftime('%d%m%Y')
                lines.append(
                    f"• {fmt_date(date)}: Item {s['item_id']} x{s['quantity']} @ {fmt_money(s['unit_price'], customer['currency'])} = {fmt_money(s['quantity'] * s['unit_price'], customer['currency'])}"
                )
        else:
            lines.append("  (No sales on this page)")
        if page == 0:
            lines.append(f"📊 *Total Sales:* {fmt_money(total_sales, customer['currency'])}")

    if scope in ["full", "payments"]:
        lines.append("\n💵 *Payments*")
        if payments_page:
            for p in payments_page:
                date = datetime.fromisoformat(p['timestamp']).strftime('%d%m%Y')
                fee_perc = p.get("fee_perc", 0.0)
                lines.append(
                    f"• {fmt_date(date)}: {fmt_money(p['local_amt'], customer['currency'])} (Fee: {fee_perc:.1f}% = {fmt_money(p['fee_amt'], customer['currency'])}) → {fmt_money(p['usd_amt'], 'USD')} @ {p['fx_rate']:.4f}"
                )
        else:
            lines.append("  (No payments on this page)")
        if page == 0:
            lines.append(f"📊 *Total Payments:* {fmt_money(total_payments_local, customer['currency'])}")
            lines.append(f"📊 *Total USD Received:* {fmt_money(total_payments_usd, 'USD')}")

    lines.append(f"\n📊 *Balance:* {fmt_money(balance, customer['currency'])}")

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="page_prev"))
    if (page + 1) * _PAGE_SIZE < (sales_count if scope in ['full','sales'] else payments_count):
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="page_next"))
    nav.append(InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu"))

    await update.callback_query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([nav]),
        parse_mode="Markdown"
    )
    return REPORT_PAGE

@require_unlock
async def paginate_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("paginate_report: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == "page_next":
        context.user_data["page"] += 1
    elif update.callback_query.data == "page_prev":
        context.user_data["page"] = max(0, context.user_data.get("page", 0) - 1)
    return await show_customer_report(update, context)


def register_customer_report_handlers(app):
    logging.info("Registering customer_report handlers")
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_customer_report_menu, pattern="^rep_cust$"),
            CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$")
        ],
        states={
            CUST_SELECT: [
                CallbackQueryHandler(select_date_range, pattern="^custrep_"),
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$")
            ],
            DATE_RANGE_SELECT: [
                CallbackQueryHandler(choose_report_scope, pattern="^daterange_"),
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$")
            ],
            CUSTOM_DATE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_date),
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$")
            ],
            REPORT_SCOPE_SELECT: [
                CallbackQueryHandler(show_customer_report, pattern="^scope_"),
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$")
            ],
            REPORT_PAGE: [
                CallbackQueryHandler(paginate_report, pattern="^page_(prev|next)$"),
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$")
            ],
        },
        fallbacks=[],
        per_message=False,
    )
    app.add_handler(conv)

