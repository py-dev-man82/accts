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
from handlers.ledger import get_ledger

def _reset_customer_report_state(context):
    for k in ['customer_id', 'start_date', 'end_date', 'page', 'scope']:
        context.user_data.pop(k, None)

async def _goto_main_menu(update, context):
    _reset_customer_report_state(context)
    from bot import start
    return await start(update, context)

(
    CUST_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_PAGE,
) = range(5)

_PAGE_SIZE = 8

@require_unlock
async def show_customer_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_customer_report_state(context)
    logging.info("show_customer_report_menu called")
    customers = [
        c for c in secure_db.all("customers")
        if c.get("type", "general") == "general"
    ]
    if not customers:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "⚠️ No general customers found.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu"),
                    InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"),
                ]
            ])
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"custrep_{c.doc_id}")
        for c in customers
    ]
    grid = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    grid.append([
        InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"),
    ])

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📄 Select a general customer to view report:",
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
        [
            InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"),
        ],
    ])
    await update.callback_query.edit_message_text(
        "Choose date range:", reply_markup=kb
    )
    return DATE_RANGE_SELECT

async def get_custom_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_custom_date")
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📅 Enter start date (DDMMYYYY):",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"),
            ]
        ])
    )
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
    data = None
    if getattr(update, "callback_query", None):
        await update.callback_query.answer()
        data = update.callback_query.data
    elif getattr(update, "message", None):
        data = "custom_date_message"

    logging.info("choose_report_scope: %s", data)

    if data == "daterange_weekly":
        context.user_data["start_date"] = datetime.now() - timedelta(days=7)
        context.user_data["end_date"] = datetime.now()
    elif data == "daterange_custom":
        return await get_custom_date(update, context)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Full Report", callback_data="scope_full")],
        [InlineKeyboardButton("🛒 Sales Only", callback_data="scope_sales")],
        [InlineKeyboardButton("💵 Payments Only", callback_data="scope_payments")],
        [
            InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"),
        ],
    ])
    if getattr(update, "callback_query", None):
        await update.callback_query.edit_message_text("Choose report scope:", reply_markup=kb)
    else:
        await update.message.reply_text("Choose report scope:", reply_markup=kb)
    return REPORT_SCOPE_SELECT

def _paginate(items, page):
    start = page * _PAGE_SIZE
    return items[start:start + _PAGE_SIZE], len(items)

def _filter_ledger(entries, start_date, end_date):
    out = []
    for e in entries:
        try:
            d = datetime.strptime(e["date"], "%d%m%Y")
        except Exception:
            continue
        if start_date <= d <= end_date:
            out.append(e)
    return out

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
    currency = customer['currency']

    # Pull both customer and general ledger entries for all-time balance
    ledger_entries_all = get_ledger("customer", cid) + get_ledger("general", cid)
    # For current date-range sales/payments display
    filtered_entries = _filter_ledger(ledger_entries_all, start_date, end_date)
    sales = [e for e in filtered_entries if e["entry_type"] == "sale"]
    payments = [e for e in filtered_entries if e["entry_type"] == "payment"]

    total_sales = sum(-e["amount"] for e in sales)
    total_payments_local = sum(e["amount"] for e in payments)

    sales_page, sales_count = _paginate(sales, page) if scope in ["full", "sales"] else ([], 0)
    payments_page, payments_count = _paginate(payments, page) if scope in ["full", "payments"] else ([], 0)

    # All-time balance, using both customer and general ledgers
    balance = sum(e["amount"] for e in ledger_entries_all)

    lines = [
        f"📄 *Report — {customer['name']}*",
        f"Period: {fmt_date(start_date.strftime('%d%m%Y'))} → {fmt_date(end_date.strftime('%d%m%Y'))}",
        f"Currency: {currency}\n"
    ]

    if scope in ["full", "sales"]:
        lines.append("🛒 *Sales*")
        if sales_page:
            for s in sales_page:
                qty = s.get("quantity", 1)
                price = s.get("unit_price", 0)
                total_val = qty * price
                lines.append(
                    f"• {fmt_date(s['date'])}: {qty} × {fmt_money(price, currency)} = {fmt_money(total_val, currency)}"
                )
        else:
            lines.append("  (No sales on this page)")
        if page == 0:
            lines.append(f"📊 *Total Sales:* {fmt_money(total_sales, currency)}")

    if scope in ["full", "payments"]:
        lines.append("\n💵 *Payments*")
        if payments_page:
            for p in payments_page:
                fee_perc = p.get('fee_perc', 0)
                fx = p.get('fx_rate', 0)
                inv_fx = 1 / fx if fx else 0
                usd_amt = p.get('usd_amt', 0)
                line = (
                    f"• {fmt_date(p['date'])}: {fmt_money(p['amount'], currency)}"
                    f" | {fee_perc:.2f}%"
                    f" | {inv_fx:.4f}"
                    f" | {fmt_money(usd_amt, 'USD')}"
                )
                if p.get('note'):
                    line += f"  📝 {p['note']}"
                lines.append(line)
        else:
            lines.append("  (No payments on this page)")
        if page == 0:
            lines.append(
                f"📊 *Total Payments:* {fmt_money(total_payments_local, currency)} → {fmt_money(sum(p.get('usd_amt',0) for p in payments), 'USD')}"
            )

    lines.append(f"\n📊 *Current Balance:* {fmt_money(balance, currency)}")

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="page_prev"))
    if (page + 1) * _PAGE_SIZE < (sales_count if scope in ['full','sales'] else payments_count):
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="page_next"))
    nav.append(InlineKeyboardButton("📄 Export PDF", callback_data="export_pdf"))
    nav.append(InlineKeyboardButton("🔙 Back", callback_data="customer_report_menu"))
    nav.append(InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))

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
        context.user_data['page'] = max(0, context.user_data.get('page', 0) - 1)
    return await show_customer_report(update, context)

@require_unlock
async def export_pdf_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = context.user_data.get('customer_id')
    customer = secure_db.table('customers').get(doc_id=cid)
    start = context.user_data.get('start_date')
    end = context.user_data.get('end_date')
    scope = context.user_data.get('scope')
    currency = customer['currency']

    ledger_entries = get_ledger("customer", cid) + get_ledger("general", cid)
    filtered_entries = _filter_ledger(ledger_entries, start, end)
    sales = [e for e in filtered_entries if e["entry_type"] == "sale"]
    payments = [e for e in filtered_entries if e["entry_type"] == "payment"]

    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 50

    pdf.setFont('Helvetica-Bold', 14)
    pdf.drawString(50, y, f"Report — {customer['name']}")
    y -= 20
    pdf.setFont('Helvetica', 10)
    pdf.drawString(50, y, f"Period: {fmt_date(start.strftime('%d%m%Y'))} → {fmt_date(end.strftime('%d%m%Y'))}")
    y -= 15
    pdf.drawString(50, y, f"Currency: {currency}")
    y -= 30

    if scope in ('full','sales'):
        pdf.setFont('Helvetica-Bold', 12)
        pdf.drawString(50, y, 'Sales:')
        y -= 20
        pdf.setFont('Helvetica', 10)
        for s in sales:
            qty = s.get("quantity", 1)
            price = s.get("unit_price", 0)
            total_val = qty * price
            line = f"{fmt_date(s['date'])}: {qty} × {fmt_money(price, currency)} = {fmt_money(total_val, currency)}"
            pdf.drawString(60, y, line)
            y -= 15
            if y<50:
                pdf.showPage(); y=height-50
        total_sales = sum(-s['amount'] for s in sales)
        pdf.setFont('Helvetica-Bold',10)
        pdf.drawString(50, y, f"Total Sales: {fmt_money(total_sales, currency)}")
        y -= 30

    if scope in ('full','payments'):
        pdf.setFont('Helvetica-Bold', 12)
        pdf.drawString(50, y, 'Payments:')
        y -= 20
        pdf.setFont('Helvetica', 10)
        for p in payments:
            fee_perc = p.get('fee_perc', 0)
            fx = p.get('fx_rate', 0)
            inv_fx = 1 / fx if fx else 0
            usd_amt = p.get('usd_amt', 0)
            line = (
                f"{fmt_date(p['date'])}: {fmt_money(p['amount'], currency)}"
                f" | {fee_perc:.2f}%"
                f" | {inv_fx:.4f}"
                f" | {fmt_money(usd_amt, 'USD')}"
            )
            pdf.drawString(60, y, line)
            y -= 15
            if y<50:
                pdf.showPage(); y=height-50
        total_local = sum(p['amount'] for p in payments)
        pdf.setFont('Helvetica-Bold',10)
        pdf.drawString(50, y, f"Total Payments: {fmt_money(total_local, currency)} → {fmt_money(sum(p.get('usd_amt',0) for p in payments), 'USD')}")
        y -= 30

    # All-time balance
    balance = sum(e["amount"] for e in ledger_entries)
    pdf.setFont('Helvetica-Bold',12)
    pdf.drawString(50, y, f"Current Balance: {fmt_money(balance, currency)}")

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    await update.callback_query.message.reply_document(
        document=buffer,
        filename=f"report_{customer['name']}_{start.strftime('%Y%m%d')}.pdf"
    )
    return REPORT_PAGE

def register_customer_report_handlers(app):
    logging.info("Registering customer_report handlers")
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_customer_report_menu, pattern="^rep_cust$"),
            CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$"),
            CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
        ],
        states={
            CUST_SELECT: [
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$"),
                CallbackQueryHandler(select_date_range, pattern="^custrep_"),
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
            ],
            DATE_RANGE_SELECT: [
                CallbackQueryHandler(choose_report_scope, pattern="^daterange_"),
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$"),
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
            ],
            CUSTOM_DATE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_date),
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$"),
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
            ],
            REPORT_SCOPE_SELECT: [
                CallbackQueryHandler(show_customer_report, pattern="^scope_"),
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$"),
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
            ],
            REPORT_PAGE: [
                CallbackQueryHandler(paginate_report, pattern="^page_(prev|next)$"),
                CallbackQueryHandler(export_pdf_report, pattern="^export_pdf$"),
                CallbackQueryHandler(show_customer_report_menu, pattern="^customer_report_menu$"),
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
            ],
        },
        fallbacks=[],
        per_message=False,
    )
    app.add_handler(conv)
    # Add these stateless handlers to allow access from any state
    app.add_handler(CallbackQueryHandler(show_customer_report_menu, pattern="^rep_cust$"))
    app.add_handler(CallbackQueryHandler(select_date_range, pattern="^custrep_\\d+$"))
    app.add_handler(CallbackQueryHandler(choose_report_scope, pattern="^daterange_"))
    app.add_handler(CallbackQueryHandler(get_custom_date, pattern="^daterange_custom$"))
    app.add_handler(CallbackQueryHandler(show_customer_report, pattern="^scope_"))
    app.add_handler(CallbackQueryHandler(paginate_report, pattern="^page_(prev|next)$"))
    app.add_handler(CallbackQueryHandler(export_pdf_report, pattern="^export_pdf$"))
    app.add_handler(CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"))
