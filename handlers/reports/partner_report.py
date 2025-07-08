# handlers/reports/partner_report.py

import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ConversationHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from handlers.utils import require_unlock, fmt_money, fmt_date
from secure_db import secure_db

# Conversation state constants
(
    R_PARTNER_SELECT,
    R_TIME_FILTER,
    R_DATE_CUSTOM,
    R_CONFIRM_RANGE,
    R_SHOW_REPORT,
) = range(5)

# Show report menu entry point
def show_partner_report_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Custom Range", callback_data="rep_part_range")],
        [InlineKeyboardButton("🗓️ This Week",     callback_data="rep_part_weekly")],
        [InlineKeyboardButton("🗓️ This Month",    callback_data="rep_part_monthly")],
        [InlineKeyboardButton("🔙 Back",           callback_data="report_menu")],
    ])
    update.callback_query.edit_message_text("Partner Report: choose period", reply_markup=kb)
    return R_PARTNER_SELECT

# Choose preset ranges or request custom
def choose_report_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update.callback_query.answer()
    data = update.callback_query.data
    today = datetime.utcnow().date()
    if data == "rep_part_weekly":
        start = today - timedelta(days=today.weekday())
        end   = start + timedelta(days=6)
    elif data == "rep_part_monthly":
        start = today.replace(day=1)
        end   = today
    else:
        return request_custom_range(update, context)
    context.user_data['report_start'] = start
    context.user_data['report_end']   = end
    return build_partner_report(update, context)

# Request custom date range
def request_custom_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update.callback_query.answer()
    update.callback_query.edit_message_text(
        "Enter date range as `DDMMYYYY-DDMMYYYY` (e.g. 01072025-07072025):"
    )
    return R_DATE_CUSTOM

# Save custom range and build report
async def save_custom_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        start_str, end_str = text.split("-")
        start = datetime.strptime(start_str, "%d%m%Y").date()
        end   = datetime.strptime(end_str,   "%d%m%Y").date()
        context.user_data['report_start'] = start
        context.user_data['report_end']   = end
    except Exception:
        await update.message.reply_text("Invalid format. Use `DDMMYYYY-DDMMYYYY`.")
        return R_DATE_CUSTOM
    return build_partner_report(update, context)

# Core report builder
def build_partner_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = context.user_data.get('report_start')
    end   = context.user_data.get('report_end')

    # Fetch data
    partners = secure_db.all('partners')
    payments = [
        p for p in secure_db.all('partner_payouts')
        if start <= datetime.strptime(p.get('date',''), "%d%m%Y").date() <= end
    ]
    sales = [
        s for s in secure_db.all('partner_sales')
        if start <= datetime.strptime(s.get('date',''), "%d%m%Y").date() <= end
    ]
    costs = [
        c for c in secure_db.all('partner_inventory')
        if start <= datetime.strptime(c.get('date',''), "%d%m%Y").date() <= end
    ]

    # Totals
    total_payments = sum(p.get('usd_amt',0) for p in payments)
    total_sales    = sum(s.get('total_value',0) for s in sales)
    total_costs    = sum(c.get('quantity',0) * c.get('unit_cost',0) for c in costs)

    # Header
    lines = [f"📊 Partner Report {fmt_date(start.strftime('%d%m%Y'))} - {fmt_date(end.strftime('%d%m%Y'))}"]
    lines.append(f"• Total Payments: {fmt_money(total_payments, 'USD')}")
    lines.append(f"• Total Sales:    {fmt_money(total_sales,    'USD')}")
    lines.append(f"• Total Costs:    {fmt_money(total_costs,    'USD')}")
    lines.append("")

    # Breakdown by partner
    for p in partners:
        pid   = p.doc_id
        pname = p.get('name','Unknown')
        pays  = [x for x in payments if x.get('partner_id')==pid]
        sells = [x for x in sales    if x.get('partner_id')==pid]
        csts  = [x for x in costs    if x.get('partner_id')==pid]
        if not (pays or sells or csts):
            continue

        lines.append(f"👤 {pname}")

        # Payments
        if pays:
            amt = sum(x.get('usd_amt',0) for x in pays)
            lines.append(f"    • Payments: {fmt_money(amt,'USD')}")

        # Sales and handling fees
        if sells:
            for s in sells:
                date = fmt_date(s.get('date',''))
                total = fmt_money(s.get('total_value',0), s.get('currency','USD'))
                lines.append(f"    • Sale on {date}: {total}")
            fees = sum(s.get('handling_fee',0) for s in sells)
            if fees:
                lines.append(f"    • Fees Deducted: {fmt_money(fees, s.get('currency','USD'))}")

        # Costs
        if csts:
            cost_sum = sum(c.get('quantity',0)*c.get('unit_cost',0) for c in csts)
            lines.append(f"    • Costs: {fmt_money(cost_sum,'USD')}")

        lines.append("")

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="rep_part_range")]])
    update.callback_query.edit_message_text("\n".join(lines), reply_markup=kb)
    return ConversationHandler.END

# Register the conversation
def register_partner_report_handlers(app):
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_partner_report_menu, pattern="^rep_part_")],
        states={
            R_PARTNER_SELECT: [CallbackQueryHandler(choose_report_scope, pattern="^rep_part_")],
            R_DATE_CUSTOM:    [MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_range)],
        },
        fallbacks=[CallbackQueryHandler(show_partner_report_menu, pattern="^rep_part_")],
        per_message=False,
    )
    app.add_handler(conv)
