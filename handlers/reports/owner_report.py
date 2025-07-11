import logging
from collections import defaultdict

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from handlers.utils import require_unlock, fmt_money
from handlers.ledger import get_balance, get_ledger
from secure_db import secure_db
from handlers.reports.report_utils import get_global_store_inventory

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

def get_verified_partner_payouts(secure_db, get_ledger):
    owner_payouts = []
    for e in get_ledger("owner", OWNER_ACCOUNT_ID):
        if e.get("entry_type") in ("payout", "payment_sent", "payout_sent"):
            owner_payouts.append(e)
    owner_set = set(
        (
            e.get("date"),
            round(abs(e.get("usd_amt", e.get("amount", 0))), 2),
            str(e.get("related_id")),
        )
        for e in owner_payouts
    )
    all_verified_payouts = []
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") in ("payout", "payment_sent", "payment"):
                key = (
                    e.get("date"),
                    round(abs(e.get("usd_amt", e.get("amount", 0))), 2),
                    str(e.get("related_id")),
                )
                if key in owner_set:
                    all_verified_payouts.append(e)
    return all_verified_payouts

def payments_by_currency(payments):
    currency_groups = defaultdict(lambda: {"local": 0.0, "usd": 0.0, "currency": ""})
    for p in payments:
        cur = p.get("currency", "USD")
        amt = p.get("amount", 0.0)
        if "usd_amt" in p and p["usd_amt"] is not None:
            usd = p["usd_amt"]
        elif cur == "USD":
            usd = amt
        else:
            usd = 0.0
        currency_groups[cur]["local"] += amt
        currency_groups[cur]["usd"] += usd
        currency_groups[cur]["currency"] = cur
    return currency_groups

def get_current_partner_inventory_with_value(secure_db, get_ledger):
    partner_inventory = defaultdict(int)
    all_sales = []
    all_stockins = []
    for partner in secure_db.all("partners"):
        # Stockin (in)
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "stockin":
                partner_inventory[e.get("item_id")] += e.get("quantity", 0)
                all_stockins.append(e)
        # Customer sales (out, assigned to partner)
        for e in get_ledger("customer", partner.doc_id):
            if e.get("entry_type") == "sale":
                partner_inventory[e.get("item_id")] -= abs(e.get("quantity", 0))
                all_sales.append(e)
        # Partner sales (out)
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "sale":
                partner_inventory[e.get("item_id")] -= abs(e.get("quantity", 0))
                all_sales.append(e)
    value_by_item = {}
    for item_id, qty in partner_inventory.items():
        if qty > 0:
            price = get_last_market_price(all_sales, all_stockins, item_id)
            value_by_item[item_id] = {"units": qty, "value": qty * price, "price": price}
    return value_by_item

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

    # --- Payments (All Customers, All Time) ---
    lines.append(f"• Payments (All Customers, All Time):")
    pay_cur = payments_by_currency(all_payments)
    total_usd = 0.0
    if pay_cur:
        for cur, group in pay_cur.items():
            local_str = fmt_money(group["local"], cur)
            usd_str = fmt_money(group["usd"], "USD")
            lines.append(f"   -  {cur}: {local_str} → {usd_str} USD")
            total_usd += group["usd"]
        lines.append(f"   Total USD received: {fmt_money(total_usd, 'USD')}")
    else:
        lines.append("   None")
    lines.append("")

    # --- Payouts (All Partners, All Time, cross-verified) ---
    all_payouts = get_verified_partner_payouts(secure_db, get_ledger)
    payout_cur = payments_by_currency(all_payouts)
    total_payouts_usd = 0.0
    lines.append(f"• Payouts (All Partners, All Time):")
    if payout_cur:
        for cur, group in payout_cur.items():
            local_str = fmt_money(group["local"], cur)
            usd_str = fmt_money(group["usd"], "USD")
            lines.append(f"   -  {cur}: {local_str} → {usd_str} USD")
            total_payouts_usd += group["usd"]
        lines.append(f"   Total USD paid: {fmt_money(total_payouts_usd, 'USD')}")
    else:
        lines.append("   None")
    lines.append("")

    # --- Current Partner Inventory on hand ---
    partner_inv = get_current_partner_inventory_with_value(secure_db, get_ledger)
    lines.append(f"• Current Partner Inventory on hand:")
    total_partner_inv_value = 0
    if partner_inv:
        for iid, v in partner_inv.items():
            lines.append(
                f"   -  {iid}: {v['units']} units × {fmt_money(v['price'], 'USD')} = {fmt_money(v['value'], 'USD')}"
            )
            total_partner_inv_value += v['value']
        lines.append(f"   Total Partner Inventory Market Value: {fmt_money(total_partner_inv_value, 'USD')}")
    else:
        lines.append("   None")
    lines.append("")

    # --- Inventory on hand ---
    # Use new utility for global store inventory
    stock_balance = get_global_store_inventory(secure_db, get_ledger)
    # Gather all sale and stockin entries for price lookup
    all_sales_for_price, all_stockins = [], []
    for store in secure_db.all("stores"):
        for e in get_ledger("store", store.doc_id):
            if e.get("entry_type") == "stockin":
                all_stockins.append(e)
    for partner in secure_db.all("partners"):
        for e in get_ledger("partner", partner.doc_id):
            if e.get("entry_type") == "stockin" and e.get("store_id") is not None:
                all_stockins.append(e)
    for ledger_type in ["customer", "store_customer", "partner"]:
        for acct in secure_db.all(ledger_type + "s"):
            for e in get_ledger(ledger_type, acct.doc_id):
                if e.get("entry_type") == "sale" and e.get("store_id") is not None:
                    all_sales_for_price.append(e)

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
