

import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
)
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from secure_db import secure_db
from handlers.utils import require_unlock, fmt_money, fmt_date
from handlers.ledger import get_ledger

# ────────────────────────────────────────────────────────────────
#  Conversation-state constants
# ────────────────────────────────────────────────────────────────
(
    PARTNER_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_PAGE,
) = range(5)

_PAGE_SIZE = 8


# ╭──────────────────────────────────────────────────────────────╮
# │  Small helpers                                              │
# ╰──────────────────────────────────────────────────────────────╯
def _reset_state(ctx):
    for k in ("partner_id", "start_date", "end_date", "page", "scope"):
        ctx.user_data.pop(k, None)


async def _goto_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline jump back to /start without losing encryption guard."""
    _reset_state(context)
    from bot import start

    return await start(update, context)


def _paginate(lst: List[dict], page: int) -> List[dict]:
    start = page * _PAGE_SIZE
    return lst[start : start + _PAGE_SIZE]


def _between(date_str: str, start: datetime, end: datetime) -> bool:
    """True if ddmmyyyy string is inside the inclusive window."""
    try:
        dt = datetime.strptime(date_str, "%d%m%Y")
    except Exception:
        return False
    return start <= dt <= end


# ╭──────────────────────────────────────────────────────────────╮
# │  Entry-point                                                │
# ╰──────────────────────────────────────────────────────────────╯
@require_unlock
async def show_partner_report_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    _reset_state(context)
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "⚠️ No partners found.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
            ),
        )
        return ConversationHandler.END

    btns = [
        InlineKeyboardButton(
            f"{p['name']} ({p['currency']})", callback_data=f"preport_{p.doc_id}"
        )
        for p in partners
    ]
    rows = [btns[i : i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])

    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📄 Select partner:",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return PARTNER_SELECT


# ╭──────────────────────────────────────────────────────────────╮
# │  Date-range selection                                       │
# ╰──────────────────────────────────────────────────────────────╯
async def select_date_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["partner_id"] = pid

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 Last 7 days", callback_data="range_week")],
            [InlineKeyboardButton("📆 Custom Range", callback_data="range_custom")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        ]
    )
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return DATE_RANGE_SELECT


async def ask_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "Enter start date DDMMYYYY:",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
        ),
    )
    return CUSTOM_DATE_INPUT


async def save_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    try:
        sd = datetime.strptime(txt, "%d%m%Y")
    except ValueError:
        await update.message.reply_text("❌ Format DDMMYYYY please.")
        return CUSTOM_DATE_INPUT

    context.user_data["start_date"] = sd
    context.user_data["end_date"] = datetime.now()
    return await choose_scope(update, context)


async def choose_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # triggered by callback OR after custom date input
    if getattr(update, "callback_query", None):
        await update.callback_query.answer()
        choice = update.callback_query.data
        if choice == "range_week":
            context.user_data["start_date"] = datetime.now() - timedelta(days=7)
            context.user_data["end_date"] = datetime.now()
        elif choice == "range_custom":
            return await ask_custom_start(update, context)

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📝 Full Report", callback_data="scope_full"),
                InlineKeyboardButton("🛒 Sales Only", callback_data="scope_sales"),
            ],
            [
                InlineKeyboardButton("💵 Payments Only", callback_data="scope_payments")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        ]
    )
    if getattr(update, "callback_query", None):
        await update.callback_query.edit_message_text(
            "Choose report scope:", reply_markup=kb
        )
    else:
        await update.message.reply_text("Choose report scope:", reply_markup=kb)
    return REPORT_SCOPE_SELECT


# ╭──────────────────────────────────────────────────────────────╮
# │  Core report view                                           │
# ╰──────────────────────────────────────────────────────────────╯
@require_unlock
async def show_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx = context.user_data
    ctx.setdefault("page", 0)
    ctx["scope"] = update.callback_query.data.split("_")[-1]

    pid = ctx["partner_id"]
    partner = secure_db.table("partners").get(doc_id=pid)
    cur = partner["currency"]
    start, end = ctx["start_date"], ctx["end_date"]

    # ── SALES (customer ledger: customer name == partner name) ────────────────
    sales: List[dict] = []
    for c in secure_db.all("customers"):
        if c["name"] == partner["name"]:
            sales += [
                e
                for e in get_ledger("customer", c.doc_id)
                if e["entry_type"] == "sale" and _between(e["date"], start, end)
            ]

    # ── PAYMENTS & EXPENSES (partner ledger) ──────────────────────────────────
    pledger = get_ledger("partner", pid)
    payments = [
        e
        for e in pledger
        if e["entry_type"] == "payment" and _between(e["date"], start, end)
    ]
    handling_fees = [
        e
        for e in pledger
        if e["entry_type"] == "handling_fee" and _between(e["date"], start, end)
    ]
    other_expenses = [
        e
        for e in pledger
        if e["entry_type"] == "expense" and _between(e["date"], start, end)
    ]

    # ── INVENTORY (partner_inventory) ─────────────────────────────────────────
    inv_rows = [r for r in secure_db.all("partner_inventory") if r["partner_id"] == pid]
    stockins = [r for r in inv_rows if _between(r["date"], start, end)]
    current_stock = [r for r in inv_rows if r["quantity"] > 0]

    # ── Totals ────────────────────────────────────────────────────────────────
    total_sales = sum(-s["amount"] for s in sales)
    total_pay_local = sum(p["amount"] for p in payments)
    total_pay_usd = sum(p.get("usd_amt", 0) for p in payments)
    total_handling = sum(-h["amount"] for h in handling_fees)
    total_other_exp = sum(-e["amount"] for e in other_expenses)

    stock_value = sum(
        r.get("market_price", r["unit_cost"]) * r["quantity"] for r in current_stock
    )
    inv_cur = current_stock[0]["currency"] if current_stock else cur

    balance = total_sales - total_pay_local - total_handling - total_other_exp

    # ── Pagination list to display (sales OR payments) ───────────────────────
    page = ctx["page"]
    paged_sales = _paginate(sales, page) if ctx["scope"] in ("full", "sales") else []
    paged_pay = _paginate(payments, page) if ctx["scope"] in ("full", "payments") else []

    # ── Build Telegram message ───────────────────────────────────────────────
    lines: List[str] = [
        f"📄 *Partner Report — {partner['name']}*",
        f"Period: {fmt_date(start.strftime('%d%m%Y'))} → {fmt_date(end.strftime('%d%m%Y'))}",
        f"Currency: {cur}\n",
    ]

    if ctx["scope"] in ("full", "sales"):
        lines.append("🛒 *Sales*")
        if paged_sales:
            for s in paged_sales:
                lines.append(f"• {fmt_date(s['date'])}: {fmt_money(-s['amount'], cur)}")
        else:
            lines.append("  (No sales on this page)")
        if page == 0:
            lines.append(f"📊 Total Sales: {fmt_money(total_sales, cur)}")

    if ctx["scope"] in ("full", "payments"):
        lines.append("\n💵 *Payments*")
        if paged_pay:
            for p in paged_pay:
                usd = fmt_money(p.get("usd_amt", 0), "USD")
                fx = p.get("fx_rate", 0)
                lines.append(
                    f"• {fmt_date(p['date'])}: {fmt_money(p['amount'], cur)} → {usd} (FX {fx:.4f})"
                )
        else:
            lines.append("  (No payments on this page)")
        if page == 0:
            lines.append(
                f"📊 Total Payments: {fmt_money(total_pay_local, cur)} → {fmt_money(total_pay_usd, 'USD')}"
            )

    if ctx["scope"] == "full":
        # Expenses
        lines.append("\n🧾 *Expenses*")
        if handling_fees:
            lines.append("• 💳 Handling Fees")
            for h in handling_fees:
                lines.append(f"   - {fmt_date(h['date'])}: {fmt_money(-h['amount'], cur)}")
            lines.append(f"📊 Total Handling Fees: {fmt_money(total_handling, cur)}")
        if other_expenses:
            lines.append("• 🧾 Other Expenses")
            for e in other_expenses:
                lines.append(f"   - {fmt_date(e['date'])}: {fmt_money(-e['amount'], cur)}")
            lines.append(f"📊 Total Other Expenses: {fmt_money(total_other_exp, cur)}")
        if not handling_fees and not other_expenses:
            lines.append("  (No expenses in this period)")

        # Inventory
        lines.append("\n📦 *Inventory*")
        if stockins:
            lines.append("• Stock-Ins:")
            for i in stockins:
                tot = i["unit_cost"] * i["quantity"]
                lines.append(
                    f"   - {fmt_date(i['date'])}: {i['quantity']} @ {fmt_money(i['unit_cost'], i['currency'])} "
                    f"= {fmt_money(tot, i['currency'])}"
                )
        else:
            lines.append("  (No stock-ins in this period)")

        if current_stock:
            lines.append("• Current Stock @ market:")
            for c in current_stock:
                mp = c.get("market_price", c["unit_cost"])
                lines.append(
                    f"   - {c['quantity']} × {fmt_money(mp, c['currency'])} = "
                    f"{fmt_money(mp * c['quantity'], c['currency'])}"
                )
            lines.append(f"📊 Stock Value: {fmt_money(stock_value, inv_cur)}")
        else:
            lines.append("  (No current stock)")

        # Summary
        lines.append("\n📊 *Financial Position*")
        lines.append(f"Balance (S − P − E): {fmt_money(balance, cur)}")
        lines.append(f"Inventory Value:     {fmt_money(stock_value, inv_cur)}")
        lines.append("─" * 36)
        lines.append(f"Total Position:      {fmt_money(balance + stock_value, cur)}")

    # ── Navigation buttons ───────────────────────────────────────────────────
    nav: List[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="page_prev"))
    # Only show Next if there *might* be more records of the current list
    show_next = (
        (ctx["scope"] in ("full", "sales") and len(sales) > (page + 1) * _PAGE_SIZE)
        or (
            ctx["scope"] in ("full", "payments")
            and len(payments) > (page + 1) * _PAGE_SIZE
        )
    )
    if show_next:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="page_next"))
    nav.append(InlineKeyboardButton("📄 Export PDF", callback_data="export_pdf"))
    nav.append(InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"))

    await update.callback_query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([nav]),
        parse_mode="Markdown",
    )
    return REPORT_PAGE


# ╭──────────────────────────────────────────────────────────────╮
# │  Pagination & PDF export                                    │
# ╰──────────────────────────────────────────────────────────────╯
@require_unlock
async def paginate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query.data == "page_next":
        context.user_data["page"] += 1
    elif update.callback_query.data == "page_prev":
        context.user_data["page"] = max(0, context.user_data["page"] - 1)
    return await show_report(update, context)


@require_unlock
async def export_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Generating PDF …")
    ctx = context.user_data
    pid = ctx["partner_id"]
    partner = secure_db.table("partners").get(doc_id=pid)
    cur = partner["currency"]
    start, end = ctx["start_date"], ctx["end_date"]
    scope = ctx["scope"]

    # Re-run the same data query (simpler than passing around lists)
    sales, payments, handling, other_exp, stockins, current_stock = [], [], [], [], [], []
    for c in secure_db.all("customers"):
        if c["name"] == partner["name"]:
            sales += [
                e
                for e in get_ledger("customer", c.doc_id)
                if e["entry_type"] == "sale" and _between(e["date"], start, end)
            ]
    pledger = get_ledger("partner", pid)
    payments = [
        e
        for e in pledger
        if e["entry_type"] == "payment" and _between(e["date"], start, end)
    ]
    handling = [
        e
        for e in pledger
        if e["entry_type"] == "handling_fee" and _between(e["date"], start, end)
    ]
    other_exp = [
        e
        for e in pledger
        if e["entry_type"] == "expense" and _between(e["date"], start, end)
    ]
    inv_rows = [r for r in secure_db.all("partner_inventory") if r["partner_id"] == pid]
    stockins = [r for r in inv_rows if _between(r["date"], start, end)]
    current_stock = [r for r in inv_rows if r["quantity"] > 0]
    inv_cur = current_stock[0]["currency"] if current_stock else cur
    stock_value = sum(
        r.get("market_price", r["unit_cost"]) * r["quantity"] for r in current_stock
    )

    # ── PDF build ────────────────────────────────────────────────────────────
    buf = BytesIO()
    pdf = canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    y = height - 40

    def line(txt: str, bold: bool = False):
        nonlocal y
        if bold:
            pdf.setFont("Helvetica-Bold", 11)
        else:
            pdf.setFont("Helvetica", 10)
        pdf.drawString(50, y, txt)
        y -= 14
        if y < 50:
            pdf.showPage()
            y = height - 40

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, f"Partner Report — {partner['name']}")
    y -= 20
    pdf.setFont("Helvetica", 10)
    line(f"Period: {fmt_date(start.strftime('%d%m%Y'))} → {fmt_date(end.strftime('%d%m%Y'))}")
    line(f"Currency: {cur}")
    y -= 10

    if scope in ("full", "sales"):
        line("Sales", bold=True)
        for s in sales:
            line(f"{fmt_date(s['date'])}: {fmt_money(-s['amount'], cur)}")
        if not sales:
            line("(none)")
        y -= 6

    if scope in ("full", "payments"):
        line("Payments", bold=True)
        for p in payments:
            usd = fmt_money(p.get('usd_amt', 0), 'USD')
            fx = p.get('fx_rate', 0)
            line(f"{fmt_date(p['date'])}: {fmt_money(p['amount'], cur)} → {usd} (FX {fx:.4f})")
        if not payments:
            line("(none)")
        y -= 6

    if scope == "full":
        # Expenses
        line("Expenses", bold=True)
        if handling:
            line("Handling Fees:")
            for h in handling:
                line(f"  {fmt_date(h['date'])}: {fmt_money(-h['amount'], cur)}")
        if other_exp:
            line("Other Expenses:")
            for e in other_exp:
                line(f"  {fmt_date(e['date'])}: {fmt_money(-e['amount'], cur)}")
        if not handling and not other_exp:
            line("(none)")
        y -= 6

        # Inventory
        line("Inventory", bold=True)
        if stockins:
            line("Stock-Ins:")
            for i in stockins:
                tot = i['unit_cost'] * i['quantity']
                line(f"  {fmt_date(i['date'])}: {i['quantity']} × {fmt_money(i['unit_cost'], i['currency'])} = {fmt_money(tot, i['currency'])}")
        if current_stock:
            line("Current Stock @ market:")
            for c in current_stock:
                mp = c.get('market_price', c['unit_cost'])
                line(f"  {c['quantity']} × {fmt_money(mp, c['currency'])} = {fmt_money(mp*c['quantity'], c['currency'])}")
            line(f"Stock Value: {fmt_money(stock_value, inv_cur)}")
        if not stockins and not current_stock:
            line("(no inventory)")
        y -= 6

    pdf.showPage()
    pdf.save()
    buf.seek(0)

    await update.callback_query.message.reply_document(
        document=buf,
        filename=f"partner_report_{partner['name']}_{start.strftime('%Y%m%d')}.pdf",
    )

    return REPORT_PAGE


# ╭──────────────────────────────────────────────────────────────╮
# │  Conversation-handler setup                                 │
# ╰──────────────────────────────────────────────────────────────╯
def register_partner_report_handlers(app):
    logging.info("▶ Register partner_report handlers")
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_partner_report_menu, pattern="^rep_part$"),
            CallbackQueryHandler(show_partner_report_menu, pattern="^partner_report_menu$"),
        ],
        states={
            PARTNER_SELECT: [
                CallbackQueryHandler(select_date_range, pattern="^preport_"),
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
            ],
            DATE_RANGE_SELECT: [
                CallbackQueryHandler(choose_scope, pattern="^range_"),
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
            ],
            CUSTOM_DATE_INPUT: [
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
                # message with date
                CallbackQueryHandler(lambda u, c: None, pattern="^$"),  # dummy
            ],
            REPORT_SCOPE_SELECT: [
                CallbackQueryHandler(show_report, pattern="^scope_"),
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
            ],
            REPORT_PAGE: [
                CallbackQueryHandler(paginate, pattern="^page_(prev|next)$"),
                CallbackQueryHandler(export_pdf, pattern="^export_pdf$"),
                CallbackQueryHandler(show_partner_report_menu, pattern="^partner_report_menu$"),
                CallbackQueryHandler(_goto_main_menu, pattern="^main_menu$"),
            ],
        },
        fallbacks=[],
        per_message=False,
    )
    app.add_handler(conv)