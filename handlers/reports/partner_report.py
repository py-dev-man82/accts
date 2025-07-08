# handlers/reports/partner_report.py

from datetime import datetime, timedelta
from io import BytesIO
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from secure_db import secure_db
from handlers.utils import require_unlock, fmt_money, fmt_date

# ────────────────────────────────────────────────────────────
# Conversation-state constants
# ────────────────────────────────────────────────────────────
(
    PARTNER_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_PAGE,
) = range(5)

# ────────────────────────────────────────────────────────────
# Pagination size
# ────────────────────────────────────────────────────────────
_PAGE_SIZE = 8


# ────────────────────────────────────────────────────────────
# Show partner report menu
# ────────────────────────────────────────────────────────────
@require_unlock
async def show_partner_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show partner report menu"""
    if update.callback_query:
        await update.callback_query.answer()
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.edit_message_text(
            "⚠️ No partners found.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="report_menu")]]
            ),
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{p['name']} ({p['currency']})", callback_data=f"partrep_{p.doc_id}")
        for p in partners
    ]
    grid = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    grid.append([InlineKeyboardButton("🔙 Back", callback_data="report_menu")])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            "📄 Select a partner to view report:",
            reply_markup=InlineKeyboardMarkup(grid)
        )
    else:
        await update.message.reply_text(
            "📄 Select a partner to view report:",
            reply_markup=InlineKeyboardMarkup(grid)
        )
    return PARTNER_SELECT


# ────────────────────────────────────────────────────────────
# Select date range
# ────────────────────────────────────────────────────────────
async def select_date_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["partner_id"] = pid

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Weekly (Last 7 days)", callback_data="daterange_weekly")],
        [InlineKeyboardButton("📆 Custom Range",           callback_data="daterange_custom")],
        [InlineKeyboardButton("🔙 Back",                   callback_data="partner_report_menu")],
    ])
    await update.callback_query.edit_message_text(
        "Choose date range:", reply_markup=kb
    )
    return DATE_RANGE_SELECT


async def get_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("📅 Enter start date (DDMMYYYY):")
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
# Choose report scope
# ────────────────────────────────────────────────────────────
async def choose_report_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data
        if data == "daterange_weekly":
            context.user_data["start_date"] = datetime.now() - timedelta(days=7)
            context.user_data["end_date"] = datetime.now()
        elif data == "daterange_custom":
            return await get_custom_date(update, context)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Full Report",    callback_data="scope_full")],
        [InlineKeyboardButton("🛒 Sales Only",     callback_data="scope_sales")],
        [InlineKeyboardButton("💵 Payments Only",  callback_data="scope_payments")],
        [InlineKeyboardButton("⚙️ Costs Only",     callback_data="scope_costs")],
        [InlineKeyboardButton("📦 Inventory Only", callback_data="scope_inventory")],
        [InlineKeyboardButton("🔙 Back",           callback_data="partner_report_menu")],
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text("Choose report scope:", reply_markup=kb)
    else:
        await update.message.reply_text("Choose report scope:", reply_markup=kb)

    return REPORT_SCOPE_SELECT


# ────────────────────────────────────────────────────────────
# Pagination helper
# ────────────────────────────────────────────────────────────
def _paginate(items, page):
    start = page * _PAGE_SIZE
    end = start + _PAGE_SIZE
    return items[start:end], len(items)


# ────────────────────────────────────────────────────────────
# Display partner report
# ────────────────────────────────────────────────────────────
async def show_partner_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    scope = update.callback_query.data.split("_")[-1]
    context.user_data["scope"] = scope
    context.user_data.setdefault("page", 0)

    pid = context.user_data["partner_id"]
    start_date = context.user_data["start_date"]
    end_date = context.user_data["end_date"]
    page = context.user_data["page"]
    partner = secure_db.table("partners").get(doc_id=pid)

    # Fetch data streams
    all_sales = [
        s for s in secure_db.all("partner_sales")
        if s["partner_id"] == pid and start_date <= datetime.fromisoformat(s["timestamp"]) <= end_date
    ]
    all_payouts = [
        p for p in secure_db.all("partner_payouts")
        if p["partner_id"] == pid and start_date <= datetime.fromisoformat(p["timestamp"]) <= end_date
    ]
    all_costs = [
        c for c in secure_db.all("partner_inventory")
        if c["partner_id"] == pid and start_date <= datetime.strptime(c["date"], "%d%m%Y") <= end_date
    ]

    # Inventory levels per item
    inventory = {}
    for c in secure_db.all("partner_inventory"):
        if c["partner_id"] == pid:
            inventory.setdefault(c["item_id"], 0)
            inventory[c["item_id"]] += c["quantity"]
    for s in secure_db.all("partner_sales"):
        if s["partner_id"] == pid:
            inventory.setdefault(s["item_id"], 0)
            inventory[s["item_id"]] -= s["quantity"]

    # Totals
    total_sales = sum(s["quantity"] * s["unit_price"] for s in all_sales)
    total_payments = sum(p["local_amt"] for p in all_payouts)
    total_costs = sum(c["quantity"] * c["cost"] for c in all_costs)

    # Paginate each list
    sales, sales_count = _paginate(all_sales, page)       if scope in ("full", "sales")      else ([], 0)
    payouts, pay_count = _paginate(all_payouts, page)     if scope in ("full", "payments")   else ([], 0)
    costs, costs_count = _paginate(all_costs, page)       if scope in ("full", "costs")      else ([], 0)
    inv_items = list(inventory.items())                   if scope in ("full", "inventory")  else []

    # Build report lines
    lines = [f"📄 *Report — {partner['name']}*"]
    lines.append(f"Period: {fmt_date(start_date.strftime('%d%m%Y'))} → {fmt_date(end_date.strftime('%d%m%Y'))}")
    lines.append(f"Currency: {partner['currency']}\n")

    if scope in ("full", "sales"):
        lines.append("🛒 *Sales*")
        if sales:
            for s in sales:
                date = fmt_date(datetime.fromisoformat(s["timestamp"]).strftime("%d%m%Y"))
                lines.append(
                    f"• {date}: Item {s['item_id']} ×{s['quantity']} @ {fmt_money(s['unit_price'], partner['currency'])} "
                    f"= {fmt_money(s['quantity']*s['unit_price'], partner['currency'])}"
                )
        else:
            lines.append("  (No sales)")
        if page == 0:
            lines.append(f"📊 *Total Sales:* {fmt_money(total_sales, partner['currency'])}")

    if scope in ("full", "payments"):
        lines.append("\n💵 *Payments*")
        if all_payouts:
            for p in payouts:
                date = fmt_date(datetime.fromisoformat(p["timestamp"]).strftime("%d%m%Y"))
                fee_perc = p.get("fee_perc", 0.0)
                lines.append(
                    f"• {date}: {fmt_money(p['local_amt'], partner['currency'])} "
                    f"(Fee: {fee_perc:.1f}% = {fmt_money(p['fee_amt'], partner['currency'])})"
                )
        else:
            lines.append("  (No payments)")
        if page == 0:
            lines.append(f"📊 *Total Payments:* {fmt_money(total_payments, partner['currency'])}")

    if scope in ("full", "costs"):
        lines.append("\n⚙️ *Costs*")
        if costs:
            for c in costs:
                date = fmt_date(c["date"])
                lines.append(
                    f"• {date}: Item {c['item_id']} ×{c['quantity']} @ {fmt_money(c['cost'], partner['currency'])} "
                    f"= {fmt_money(c['quantity']*c['cost'], partner['currency'])}"
                )
        else:
            lines.append("  (No costs)")
        if page == 0:
            lines.append(f"📊 *Total Costs:* {fmt_money(total_costs, partner['currency'])}")

    if scope in ("full", "inventory"):
        lines.append("\n📦 *Inventory*")
        if inv_items:
            for item_id, qty in inv_items[page*_PAGE_SIZE:(page+1)*_PAGE_SIZE]:
                lines.append(f"• Item {item_id}: {qty}")
        else:
            lines.append("  (No inventory records)")

    # Net position only on first page
    if page == 0 and scope in ("full",):
        net = total_sales - total_payments - total_costs
        lines.append(f"\n📊 *Net Position:* {fmt_money(net, partner['currency'])}")

    # Navigation buttons
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="page_prev"))
    # Determine if next page exists
    total_items = {
        "sales":   sales_count,
        "payments": pay_count,
        "costs":   costs_count,
        "inventory": len(inv_items)
    }.get(scope, 0)
    if (page+1)*_PAGE_SIZE < total_items:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="page_next"))
    nav.append(InlineKeyboardButton("📄 Export PDF",       callback_data="export_pdf"))
    nav.append(InlineKeyboardButton("🔙 Back",             callback_data="partner_report_menu"))

    kb = InlineKeyboardMarkup([nav])
    await update.callback_query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode="Markdown")
    return REPORT_PAGE


# ────────────────────────────────────────────────────────────
# Pagination and PDF export handler
# ────────────────────────────────────────────────────────────
@require_unlock
async def paginate_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = update.callback_query.data
    if data == "page_next":
        context.user_data["page"] += 1
    elif data == "page_prev":
        context.user_data["page"] = max(0, context.user_data.get("page", 0) - 1)
    return await show_partner_report(update, context)


@require_unlock
async def export_pdf_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    # Rebuild full-range report
    context.user_data["page"] = 0
    # Invoke the same data gathering
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 50

    pid = context.user_data["partner_id"]
    start_date = context.user_data["start_date"]
    end_date = context.user_data["end_date"]
    partner = secure_db.table("partners").get(doc_id=pid)

    # Header
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, f"Report — {partner['name']}")
    y -= 20
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, y, f"Period: {fmt_date(start_date.strftime('%d%m%Y'))} → {fmt_date(end_date.strftime('%d%m%Y'))}")
    y -= 15
    pdf.drawString(50, y, f"Currency: {partner['currency']}")
    y -= 30

    # Re-generate all data
    # (similar to show_partner_report, but without pagination)
    # ... you’d copy the data-fetch logic here and draw lines similarly ...

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    await update.callback_query.message.reply_document(
        document=buffer,
        filename=f"report_{partner['name']}_{start_date.strftime('%Y%m%d')}.pdf"
    )
    return REPORT_PAGE


# ────────────────────────────────────────────────────────────
# Register handlers
# ────────────────────────────────────────────────────────────
def register_partner_report_handlers(app):
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_partner_report_menu, pattern="^rep_part$"),
            CallbackQueryHandler(show_partner_report_menu, pattern="^partner_report_menu$")
        ],
        states={
            PARTNER_SELECT:       [CallbackQueryHandler(select_date_range,    pattern="^partrep_")],
            DATE_RANGE_SELECT:    [CallbackQueryHandler(choose_report_scope, pattern="^daterange_")],
            CUSTOM_DATE_INPUT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_date)],
            REPORT_SCOPE_SELECT:  [CallbackQueryHandler(show_partner_report,  pattern="^scope_")],
            REPORT_PAGE:          [
                CallbackQueryHandler(paginate_report,    pattern="^page_(prev|next)$"),
                CallbackQueryHandler(export_pdf_report, pattern="^export_pdf$"),
                CallbackQueryHandler(show_partner_report_menu, pattern="^partner_report_menu$")
            ],
        },
        fallbacks=[],
        per_message=False,
    )
    app.add_handler(conv)
