# handlers/reports/partner_report.py

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
    PARTNER_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_PAGE,
) = range(5)

# Pagination size
_PAGE_SIZE = 8

@require_unlock
async def show_partner_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("show_partner_report_menu called")
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "⚠️ No partners found.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="report_menu")]]
            )
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{p['name']}", callback_data=f"partrep_{p.doc_id}")
        for p in partners
    ]
    grid = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    grid.append([InlineKeyboardButton("🔙 Back", callback_data="report_menu")])

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📄 Select a partner to view report:",
        reply_markup=InlineKeyboardMarkup(grid)
    )
    return PARTNER_SELECT

async def select_date_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("select_date_range: %s", update.callback_query.data)
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["partner_id"] = pid

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Weekly (Last 7 days)", callback_data="daterange_weekly")],
        [InlineKeyboardButton("📆 Custom Range", callback_data="daterange_custom")],
        [InlineKeyboardButton("🔙 Back", callback_data="partner_report_menu")],
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
        [InlineKeyboardButton("📝 Full Report",   callback_data="scope_full")],
        [InlineKeyboardButton("🛒 Sales Only",    callback_data="scope_sales")],
        [InlineKeyboardButton("💵 Payments Only", callback_data="scope_payments")],
        [InlineKeyboardButton("⚙️ Costs Only",    callback_data="scope_costs")],
        [InlineKeyboardButton("📦 Inventory Only", callback_data="scope_inventory")],
        [InlineKeyboardButton("🔙 Back",          callback_data="partner_report_menu")],
    ])
    await update.callback_query.edit_message_text(
        "Choose report scope:", reply_markup=kb
    )
    return REPORT_SCOPE_SELECT

# Helper for pagination

def _paginate(items, page):
    start = page * _PAGE_SIZE
    return items[start:start + _PAGE_SIZE], len(items)

@require_unlock
async def show_partner_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("show_partner_report: %s", update.callback_query.data)
    await update.callback_query.answer()
    scope = update.callback_query.data.split("_")[-1]
    context.user_data["scope"] = scope
    context.user_data.setdefault("page", 0)

    pid = context.user_data["partner_id"]
    start_date = context.user_data["start_date"]
    end_date = context.user_data["end_date"]
    page = context.user_data["page"]
    partner = secure_db.table("partners").get(doc_id=pid)

    # Data sources
    sales_all = [s for s in secure_db.all("partner_sales")
                 if s["partner_id"] == pid and start_date <= datetime.fromisoformat(s["timestamp"]) <= end_date]
    payouts_all = [p for p in secure_db.all("payouts")
                   if p["partner_id"] == pid and start_date <= datetime.fromisoformat(p["timestamp"]) <= end_date]
    costs_all = [c for c in secure_db.all("stockin")
                 if c["partner_id"] == pid and start_date <= datetime.fromisoformat(c["timestamp"]) <= end_date]

    # Inventory derived: map item_id to in minus sold
    inv = {}
    for c in costs_all:
        inv[c['item_id']] = inv.get(c['item_id'], 0) + c['quantity']
    for s in sales_all:
        inv[s['item_id']] = inv.get(s['item_id'], 0) - s['quantity']

    # Totals
    total_sales = sum(s['quantity'] * s['unit_price'] for s in sales_all)
    total_payments = sum(p['local_amt'] for p in payouts_all)
    total_costs = sum(c['quantity'] * c['unit_cost'] for c in costs_all)
    balance = total_sales - total_payments - total_costs

    # Paginate lists
    sales_page, sales_count = _paginate(sales_all, page) if scope in ("full","sales") else ([],0)
    payouts_page, payouts_count = _paginate(payouts_all, page) if scope in ("full","payments") else ([],0)
    costs_page, costs_count = _paginate(costs_all, page) if scope in ("full","costs") else ([],0)
    inv_items = list(inv.items())
    inv_page, inv_count = _paginate(inv_items, page) if scope in ("full","inventory") else ([],0)

    # Build lines
    lines = [
        f"📄 *Report — {partner['name']}*",
        f"Period: {fmt_date(start_date.strftime('%d%m%Y'))} → {fmt_date(end_date.strftime('%d%m%Y'))}",
        f"Currency: {partner['currency']}\n"
    ]

    # Sales section
    if scope in ("full","sales"):
        lines.append("🛒 *Sales*")
        if sales_page:
            for s in sales_page:
                date = fmt_date(datetime.fromisoformat(s['timestamp']).strftime('%d%m%Y'))
                lines.append(f"• {date}: Item {s['item_id']} ×{s['quantity']} @ {fmt_money(s['unit_price'],partner['currency'])} = {fmt_money(s['quantity']*s['unit_price'],partner['currency'])}")
        else:
            lines.append("  (No sales)")
        if page==0:
            lines.append(f"📊 *Total Sales:* {fmt_money(total_sales,partner['currency'])}")

    # Payments section
    if scope in ("full","payments"):
        lines.append("\n💵 *Payments*")
        if payouts_page:
            for p in payouts_page:
                date = fmt_date(datetime.fromisoformat(p['timestamp']).strftime('%d%m%Y'))
                fee_perc = p.get('fee_perc',0.0)
                lines.append(f"• {date}: {fmt_money(p['local_amt'],partner['currency'])} (Fee: {fee_perc:.1f}% = {fmt_money(p['fee_amt'],partner['currency'])})")
        else:
            lines.append("  (No payments)")
        if page==0:
            lines.append(f"📊 *Total Payments:* {fmt_money(total_payments,partner['currency'])}")

    # Costs section
    if scope in ("full","costs"):
        lines.append("\n⚙️ *Costs*")
        if costs_page:
            for c in costs_page:
                date = fmt_date(datetime.fromisoformat(c['timestamp']).strftime('%d%m%Y'))
                lines.append(f"• {date}: Item {c['item_id']} ×{c['quantity']} @ {fmt_money(c['unit_cost'],partner['currency'])} = {fmt_money(c['quantity']*c['unit_cost'],partner['currency'])}")
        else:
            lines.append("  (No costs)")
        if page==0:
            lines.append(f"📊 *Total Costs:* {fmt_money(total_costs,partner['currency'])}")

    # Inventory section
    if scope in ("full","inventory"):
        lines.append("\n📦 *Inventory*")
        if inv_page:
            for item_id, qty in inv_page:
                lines.append(f"• Item {item_id}: {qty}")
        else:
            lines.append("  (No inventory)")

    # Balance
    lines.append(f"\n📊 *Net Position:* Sales {fmt_money(total_sales,partner['currency'])} − Payments {fmt_money(total_payments,partner['currency'])} − Costs {fmt_money(total_costs,partner['currency'])} = {fmt_money(balance,partner['currency'])}")

    # Nav buttons
    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="page_prev"))
    if (page+1)*_PAGE_SIZE < max(sales_count,payouts_count,costs_count,inv_count):
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="page_next"))
    nav.append(InlineKeyboardButton("📄 Export PDF", callback_data="export_pdf"))
    nav.append(InlineKeyboardButton("🔙 Back", callback_data="partner_report_menu"))

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
        context.user_data['page'] += 1
    elif update.callback_query.data == "page_prev":
        context.user_data['page'] = max(0, context.user_data.get('page',0)-1)
    return await show_partner_report(update, context)

@require_unlock
async def export_pdf_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export the current partner report as a PDF."""
    await update.callback_query.answer()
    # PDF export logic (reuse full-range data)
    # ... similar to customer report but with partner data streams
    return REPORT_PAGE


def register_partner_report_handlers(app):
    logging.info("Registering partner_report handlers")
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_partner_report_menu, pattern="^rep_partner$"),
            CallbackQueryHandler(show_partner_report_menu, pattern="^partner_report_menu$"),
        ],
        states={
            PARTNER_SELECT:      [CallbackQueryHandler(select_date_range, pattern="^partrep_")],
            DATE_RANGE_SELECT:   [CallbackQueryHandler(choose_report_scope, pattern="^daterange_")],
            CUSTOM_DATE_INPUT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_date)],
            REPORT_SCOPE_SELECT: [CallbackQueryHandler(show_partner_report, pattern="^scope_")],
            REPORT_PAGE:         [
                CallbackQueryHandler(paginate_report,    pattern="^page_(prev|next)$"),
                CallbackQueryHandler(export_pdf_report, pattern="^export_pdf$"),
                CallbackQueryHandler(show_partner_report_menu, pattern="^partner_report_menu$"),
            ],
        },
        fallbacks=[],
        per_message=False,
    )
    app.add_handler(conv)
