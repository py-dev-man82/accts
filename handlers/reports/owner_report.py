import logging
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money
from handlers.ledger import get_balance, get_ledger
from secure_db import secure_db

OWNER_ACCOUNT_ID = "POT"
(
    SHOW_POSITION,
) = range(1)

logger = logging.getLogger("owner_position")

def get_last_market_price(sales_entries, stockin_entries, item_id):
    relevant_sales = [e for e in sales_entries if e.get("item_id") == item_id]
    if relevant_sales:
        latest = sorted(relevant_sales, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", latest.get("unit_cost", 0))
    relevant_stockins = [e for e in stockin_entries if e.get("item_id") == item_id]
    if relevant_stockins:
        latest = sorted(relevant_stockins, key=lambda x: (x.get("date", ""), x.get("timestamp", "")), reverse=True)[0]
        return latest.get("unit_price", 0)
    return 0

def get_all_sales_payments(secure_db, get_ledger):
    all_sales = []
    all_payments = []
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            for e in get_ledger(acct_type, cust.doc_id):
                if e.get("entry_type") == "sale":
                    all_sales.append(e)
                elif e.get("entry_type") == "payment":
                    all_payments.append(e)
    return all_sales, all_payments

def get_all_partner_sales(secure_db, get_ledger):
    partner_sales = []
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "sale":
                partner_sales.append(e)
    return partner_sales

def get_all_payouts(secure_db, get_ledger):
    all_payouts = []
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") in ("payout", "payment_sent"):
                all_payouts.append(e)
    return all_payouts

def get_combined_inventory(secure_db, get_ledger):
    stock_balance = defaultdict(int)
    all_stockins = []
    for store in secure_db.all("stores"):
        for e in get_ledger("store", store.doc_id):
            if e.get("entry_type") == "stockin":
                stock_balance[e.get("item_id")] += e.get("quantity", 0)
                all_stockins.append(e)
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "stockin" and e.get("store_id") is not None:
                stock_balance[e.get("item_id")] += e.get("quantity", 0)
                all_stockins.append(e)
    all_sales = []
    for cust in secure_db.all("customers"):
        for acct_type in ["customer", "store_customer"]:
            for e in get_ledger(acct_type, cust.doc_id):
                if e.get("entry_type") == "sale":
                    stock_balance[e.get("item_id")] -= abs(e.get("quantity", 0))
                    all_sales.append(e)
    return stock_balance, all_sales, all_stockins

def payments_by_currency(payments):
    currency_groups = defaultdict(lambda: {"local": 0.0, "usd": 0.0, "currency": ""})
    for p in payments:
        cur = p.get("currency", "USD")
        amt = p.get("amount", 0.0)
        usd = p.get("usd_amt", amt if cur == "USD" else 0.0)
        currency_groups[cur]["local"] += amt
        currency_groups[cur]["usd"] += usd
        currency_groups[cur]["currency"] = cur
    return currency_groups

@require_unlock
async def show_owner_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()

    lines = []
    lines.append(f"📊 **Current Owner Position** 📊\n")

    # --- Cash Position ---
    cash = get_balance("owner", OWNER_ACCOUNT_ID)
    lines.append(f"• Cash Position (Owner USD account): {fmt_money(cash, 'USD')}\n")

    # --- Sales (All Customers, All Time) ---
    all_sales, all_payments = get_all_sales_payments(secure_db, get_ledger)
    sales_summary = defaultdict(lambda: {"units": 0, "value": 0.0})
    for s in all_sales:
        iid = s.get("item_id", "?")
        units = abs(s.get("quantity", 0))
        value = abs(units * s.get("unit_price", s.get("unit_cost", 0)))
        sales_summary[iid]["units"] += units
        sales_summary[iid]["value"] += value

    lines.append(f"• Sales (All Customers, All Time):")
    if sales_summary:
        for iid, d in sales_summary.items():
            avg = (d["value"] / d["units"]) if d["units"] else 0.0
            lines.append(f"   -  {iid}: {d['units']} units, {fmt_money(d['value'], 'USD')} (Avg: {fmt_money(avg, 'USD')})")
    else:
        lines.append("   None")
    lines.append("")

    # --- Partner Sales (All Partners, All Time) ---
    partner_sales = get_all_partner_sales(secure_db, get_ledger)
    partner_sales_summary = defaultdict(lambda: {"units": 0, "value": 0.0})
    for s in partner_sales:
        iid = s.get("item_id", "?")
        units = abs(s.get("quantity", 0))
        value = abs(units * s.get("unit_price", s.get("unit_cost", 0)))
        partner_sales_summary[iid]["units"] += units
        partner_sales_summary[iid]["value"] += value

    lines.append(f"• Partner Sales (All Partners, All Time):")
    if partner_sales_summary:
        for iid, d in partner_sales_summary.items():
            avg = (d["value"] / d["units"]) if d["units"] else 0.0
            lines.append(f"   -  {iid}: {d['units']} units, {fmt_money(d['value'], 'USD')} (Avg: {fmt_money(avg, 'USD')})")
    else:
        lines.append("   None")
    lines.append("")

    # --- Inventory reconciliation (sales not yet allocated to partners) ---
    lines.append(f"• Inventory reconciliation (sales not yet allocated to partners):")
    items_all = set(list(sales_summary.keys()) + list(partner_sales_summary.keys()))
    any_rec = False
    for iid in items_all:
        rec_units = sales_summary[iid]["units"] - partner_sales_summary[iid]["units"]
        if rec_units != 0:
            any_rec = True
            lines.append(f"   -  {iid}: {rec_units} units")
    if not any_rec:
        lines.append("   All reconciled (0 units difference)")
    lines.append("")

    # --- Payments (All Customers, All Time) ---
    lines.append(f"• Payments (All Customers, All Time):")
    pay_cur = payments_by_currency(all_payments)
    total_usd = 0.0
    if pay_cur:
        for cur, group in pay_cur.items():
            cur_label = cur
            if cur == "AUD":
                cur_label = "A$"
            elif cur == "GBP":
                cur_label = "£"
            elif cur == "USD":
                cur_label = "$"
            local_str = fmt_money(group["local"], cur)
            usd_str = fmt_money(group["usd"], "USD")
            lines.append(f"   -  {cur}: {local_str} → {usd_str} USD")
            total_usd += group["usd"]
        lines.append(f"   Total USD received: {fmt_money(total_usd, 'USD')}")
    else:
        lines.append("   None")
    lines.append("")

    # --- Payouts (All Partners, All Time) ---
    all_payouts = get_all_payouts(secure_db, get_ledger)
    payout_cur = payments_by_currency(all_payouts)
    total_payouts_usd = 0.0
    lines.append(f"• Payouts (All Partners, All Time):")
    if payout_cur:
        for cur, group in payout_cur.items():
            cur_label = cur
            if cur == "AUD":
                cur_label = "A$"
            elif cur == "GBP":
                cur_label = "£"
            elif cur == "USD":
                cur_label = "$"
            local_str = fmt_money(group["local"], cur)
            usd_str = fmt_money(group["usd"], "USD")
            lines.append(f"   -  {cur}: {local_str} → {usd_str} USD")
            total_payouts_usd += group["usd"]
        lines.append(f"   Total USD paid: {fmt_money(total_payouts_usd, 'USD')}")
    else:
        lines.append("   None")
    lines.append("")

    # --- Inventory on hand ---
    stock_balance, all_sales_for_price, all_stockins = get_combined_inventory(secure_db, get_ledger)
    lines.append(f"• Inventory on hand:")
    inventory_lines = []
    total_market_value = 0
    for item_id, qty in stock_balance.items():
        if qty > 0:
            last_price = get_last_market_price(all_sales_for_price, all_stockins, item_id)
            item_value = qty * last_price
            total_market_value += item_value
            inventory_lines.append(f"   -  {item_id}: {qty} units × {fmt_money(last_price, 'USD')} = {fmt_money(item_value, 'USD')}")
    if inventory_lines:
        lines.extend(inventory_lines)
        lines.append(f"   Total Inventory Market Value: {fmt_money(total_market_value, 'USD')}")
    else:
        lines.append("   None")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="rep_owner")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])
    msg = "\n".join(lines)
    if update.callback_query:
        await update.callback_query.edit_message_text(msg[:4096], reply_markup=kb, parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(msg[:4096], reply_markup=kb, parse_mode="Markdown")
    return SHOW_POSITION

def register_owner_report_handlers(app):
    app.add_handler(CallbackQueryHandler(show_owner_position, pattern="^rep_owner$"))
    app.add_handler(CommandHandler("owner_position", show_owner_position))
