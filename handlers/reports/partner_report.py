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
from handlers.ledger import get_ledger, get_balance

(
    PARTNER_SELECT,
    DATE_RANGE_SELECT,
    CUSTOM_DATE_INPUT,
    REPORT_SCOPE_SELECT,
    REPORT_PAGE,
) = range(5)

_PAGE_SIZE = 8

def _reset_partner_report_state(context):
    for k in ['partner_id', 'start_date', 'end_date', 'page', 'scope']:
        context.user_data.pop(k, None)

def _is_partner_entity(p):
    # Only those in partners table, ignore stores/customers.
    return True

@require_unlock
async def show_partner_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset_partner_report_state(context)
    logging.info("show_partner_report_menu called")
    partners = secure_db.all("partners")
    if not partners:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "⚠️ No partners found.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="partner_report_menu")],
            ])
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{p['name']} ({p['currency']})", callback_data=f"partrep_{p.doc_id}")
        for p in partners if _is_partner_entity(p)
    ]
    grid = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    grid.append([InlineKeyboardButton("🔙 Back", callback_data="partner_report_menu")])

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
        [InlineKeyboardButton("📆 Custom Range",          callback_data="daterange_custom")],
        [
            InlineKeyboardButton("🔙 Back", callback_data="partner_report_menu"),
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
            [InlineKeyboardButton("🔙 Back", callback_data="partner_report_menu")],
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
    context.user_data["end_date"]   = datetime.now()
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
        context.user_data["end_date"]   = datetime.now()
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
async def show_partner_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("show_partner_report: page=%s scope=%s", context.user_data.get("page"), context.user_data.get("scope"))
    await update.callback_query.answer()
    scope = update.callback_query.data.split("_")[-1]
    context.user_data["scope"] = scope
    context.user_data.setdefault("page", 0)

    pid        = context.user_data["partner_id"]
    start_date = context.user_data["start_date"]
    end_date   = context.user_data["end_date"]
    page       = context.user_data["page"]
    partner    = secure_db.table("partners").get(doc_id=pid)
    currency   = partner['currency']

    # Unified ledger logic
    ledger_entries = get_ledger("partner", pid)
    filtered_entries = _filter_ledger(ledger_entries, start_date, end_date)
    sales    = [e for e in filtered_entries if e["entry_type"] == "sale"]
    payments = [e for e in filtered_entries if e["entry_type"] == "payment"]
    costs    = [e for e in filtered_entries if e["entry_type"] == "cost"]
    # inventory comes from last known costs minus sales
    inventory_map = {}
    for c in costs:
        iid = c['item_id']
        inventory_map.setdefault(iid, 0)
        inventory_map[iid] += c['quantity']
    for s in sales:
        iid = s['item_id']
        inventory_map.setdefault(iid, 0)
        inventory_map[iid] -= s['quantity']

    # Live lookup market price and valuation
    inv_values = {}
    for item_id, qty in inventory_map.items():
        item_rec = secure_db.table("items").get(doc_id=int(item_id))
        price = item_rec.get("current_price", 0.0) if item_rec else 0.0
        inv_values[item_id] = qty * price
    total_inventory_value = sum(inv_values.values())

    # Totals
    total_sales        = sum(s["quantity"] * s["unit_price"] for s in sales)
    total_fees         = sum(s.get("handling_fee", 0) for s in sales)
    total_payments_loc = sum(p["amount"] for p in payments)
    total_payments_usd = sum(p.get("usd_amt", 0) for p in payments)
    total_costs        = sum(c["quantity"] * c["unit_cost"] for c in costs)
    balance            = total_sales - total_costs - total_fees - total_payments_loc
    total_cash_position = balance + total_inventory_value

    sales_page,    sales_count    = _paginate(sales,    page) if scope in ["full","sales"]     else ([],0)
    payouts_page,  payouts_count  = _paginate(payments, page) if scope in ["full","payments"]  else ([],0)
    costs_page,    costs_count    = _paginate(costs,    page) if scope in ["full","costs"]     else ([],0)
    inv_items                    = list(inventory_map.items())
    inv_page,     inv_count      = _paginate(inv_items, page) if scope in ["full","inventory"] else ([],0)

    lines = [
        f"📄 *Report — {partner['name']}*",
        f"Period: {fmt_date(start_date.strftime('%d%m%Y'))} → {fmt_date(end_date.strftime('%d%m%Y'))}",
        f"Currency: {currency}\n"
    ]

    # SALES
    if scope in ["full","sales"]:
        lines.append("🛒 *Sales*")
        if sales_page:
            for s in sales_page:
                store = secure_db.table("stores").get(doc_id=s.get("store_id")) if s.get("store_id") else None
                store_str = f"@{store['name']}" if store else ""
                line = f"• {fmt_date(s['date'])}: Item {s['item_id']} ×{s['quantity']} @ {fmt_money(s['unit_price'], currency)} = {fmt_money(s['quantity'] * s['unit_price'], currency)} {store_str}"
                note = s.get('note', '')
                if note:
                    line += f"  📝 {note}"
                lines.append(line)
        else:
            lines.append("  (No sales on this page)")
        if page == 0:
            lines.append(f"📊 *Total Sales:* {fmt_money(total_sales, currency)}")
            if total_fees:
                lines.append(f"📊 *Handling Fees Deducted:* {fmt_money(total_fees, currency)}")

    # PAYMENTS
    if scope in ["full","payments"]:
        lines.append("\n💵 *Payments*")
        if payouts_page:
            for p in payouts_page:
                fx = p.get("fx_rate")
                usd = p.get("usd_amt")
                line = f"• {fmt_date(p['date'])}: {fmt_money(p['amount'], currency)}"
                if fx is not None:
                    line += f"  FX {fx:.4f}"
                if usd is not None:
                    line += f"  USD {usd:.2f}"
                if p.get('note'):
                    line += f"  📝 {p['note']}"
                lines.append(line)
        else:
            lines.append("  (No payments on this page)")
        if page == 0:
            lines.append(f"📊 *Total Payments:* {fmt_money(total_payments_loc, currency)}")
            lines.append(f"📊 *Total USD Paid:* {fmt_money(total_payments_usd, 'USD')}")

    # COSTS
    if scope in ["full","costs"]:
        lines.append("\n⚙️ *Costs*")
        if costs_page:
            for c in costs_page:
                store = secure_db.table("stores").get(doc_id=c.get("store_id")) if c.get("store_id") else None
                store_str = f"@{store['name']}" if store else ""
                line = f"• {fmt_date(c['date'])}: Item {c['item_id']} ×{c['quantity']} @ {fmt_money(c['unit_cost'], currency)} = {fmt_money(c['quantity'] * c['unit_cost'], currency)} {store_str}"
                note = c.get('note', '')
                if note:
                    line += f"  📝 {note}"
                lines.append(line)
        else:
            lines.append("  (No costs on this page)")
        if page == 0:
            lines.append(f"📊 *Total Costs:* {fmt_money(total_costs, currency)}")

    # INVENTORY
    if scope in ["full","inventory"]:
        lines.append("\n📦 *Inventory*")
        if inv_page:
            for item_id, qty in inv_page:
                item_rec = secure_db.table("items").get(doc_id=int(item_id))
                price = item_rec.get("current_price", 0.0) if item_rec else 0.0
                value = inv_values.get(item_id, 0.0)
                lines.append(
                    f"• Item {item_id}: {qty} units × {fmt_money(price, currency)} = {fmt_money(value, currency)}"
                )
        else:
            lines.append("  (No inventory on this page)")
        if page == 0:
            lines.append(f"\n📊 *Total Inventory Value:* {fmt_money(total_inventory_value, currency)}")

    # BALANCE & TOTAL CASH POSITION
    lines.append(f"\n📊 *Balance:* {fmt_money(balance, currency)}")
    lines.append(f"📊 *Total Cash Position:* {fmt_money(total_cash_position, currency)}")

    total_items_current = {
        "sales":    sales_count,
        "payments": payouts_count,
        "costs":    costs_count,
        "inventory": inv_count,
    }.get(scope if scope != "full" else "sales", 0)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="page_prev"))
    if (page + 1) * _PAGE_SIZE < total_items_current:
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
        context.user_data['page'] = max(0, context.user_data.get('page', 0) - 1)
    return await show_partner_report(update, context)

@require_unlock
async def export_pdf_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🖨️ PDF export for partner report coming soon!")
    return REPORT_PAGE

def register_partner_report_handlers(app):
    logging.info("Registering partner_report handlers")
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_partner_report_menu, pattern="^rep_part$"),
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
