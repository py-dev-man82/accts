# handlers/owner.py

import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from secure_db import secure_db
from handlers.utils import require_unlock

# ───────────────────────────────────────────
# Conversation state constants
# ───────────────────────────────────────────
(
    O_PRICE_SELECT,
    O_PRICE_INPUT,
    O_PRICE_CONFIRM,
    O_POT_ACTION,
    O_POT_INPUT,
    O_POT_NOTE,
    O_POT_CONFIRM,
) = range(7)

# ───────────────────────────────────────────
# Self-healing schema tweaks
# ───────────────────────────────────────────
def ensure_owner_schema() -> None:
    _ = secure_db.all("owner_adjustments")  # auto-create if missing
    for item in secure_db.all("items"):
        if "current_price" not in item:
            secure_db.update("items", {"current_price": 0.0}, [item.doc_id])


ensure_owner_schema()

# ════════════════════════════════════════════════════════════
# MAIN MENU
# ════════════════════════════════════════════════════════════
async def show_owner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Overview", callback_data="owner_overview")],
            [
                InlineKeyboardButton("💲 Set Market Prices", callback_data="owner_set_prices")
            ],
            [InlineKeyboardButton("🏦 Adjust POT Balance", callback_data="owner_adjust_pot")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ]
    )
    await update.callback_query.edit_message_text(
        "👑 Owner: choose an action", reply_markup=kb
    )

# ════════════════════════════════════════════════════════════
# OVERVIEW  (cash & per-item stock reconciliation)
# ════════════════════════════════════════════════════════════
@require_unlock
async def show_owner_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    # ---------- POT: USD in ----------
    pot_in = 0.0
    for r in secure_db.all("customer_payments"):
        pot_in += r.get(
            "usd_amt",
            (r.get("local_amt", 0) - r.get("fee_amt", 0))
            / (r.get("fx_rate", 1.0) or 1.0),
        )

    # ---------- POT: USD out ----------
    pot_out = 0.0
    for r in secure_db.all("partner_payouts"):
        pot_out += r.get(
            "usd_amt",
            (r.get("local_amt", 0) - r.get("fee_amt", 0))
            / (r.get("fx_rate", 1.0) or 1.0),
        )

    adjustments = sum(r.get("amount", 0.0) for r in secure_db.all("owner_adjustments"))
    pot_balance = pot_in - pot_out + adjustments

    # ---------- Build per-item owner-side inventory ----------
    owner_qty = {}
    for sale in secure_db.all("sales"):
        item_id = sale["item_id"]
        owner_qty[item_id] = owner_qty.get(item_id, 0) + sale["quantity"]

    # ---------- Build per-item partner-side inventory ----------
    partner_qty = {}
    for inv in secure_db.all("partner_inventory"):
        item_id = inv["item_id"]
        partner_qty[item_id] = partner_qty.get(item_id, 0) + inv["quantity"]

    # ---------- Compose per-item rows ----------
    rows = []
    grand_owner_qty = grand_partner_qty = 0
    grand_owner_val = grand_partner_val = 0.0

    for item in secure_db.all("items"):
        iid = item.doc_id
        price = item.get("current_price", 0.0)
        oqty = owner_qty.get(iid, 0)
        pqty = partner_qty.get(iid, 0)
        dqty = oqty - pqty

        if oqty == pqty == 0:
            continue  # skip items not present anywhere

        oval = oqty * price
        pval = pqty * price
        dval = dqty * price

        rows.append((item["name"], oqty, pqty, dqty, oval, pval, dval))

        grand_owner_qty += oqty
        grand_partner_qty += pqty
        grand_owner_val += oval
        grand_partner_val += pval

    diff_qty_total = grand_owner_qty - grand_partner_qty
    diff_val_total = grand_owner_val - grand_partner_val
    stock_status = "✅ Balanced" if diff_qty_total == 0 else "⚠️ Unbalanced"

    # ---------- Store-side inventory USD value ----------
    store_inventory_val = grand_owner_val

    # ---------- Cash reconciliation ----------
    owner_cash = pot_balance + store_inventory_val
    partners_position_usd = 0.0

    # rebuild partners position (USD) – cash + inventory
    for partner in secure_db.all("partners"):
        # partner balance (USD)
        bal_usd = 0.0
        for s in secure_db.all("sales"):
            if s.get("partner_id") == partner.doc_id:
                bal_usd += s["quantity"] * s["unit_price"]
        for pp in secure_db.all("partner_payouts"):
            if pp.get("partner_id") == partner.doc_id:
                bal_usd -= pp.get(
                    "usd_amt",
                    (pp.get("local_amt", 0) - pp.get("fee_amt", 0))
                    / (pp.get("fx_rate", 1.0) or 1.0),
                )
        # partner inventory value
        inv_val = 0.0
        for inv in secure_db.all("partner_inventory"):
            if inv["partner_id"] == partner.doc_id:
                price = secure_db.table("items").get(doc_id=inv["item_id"]).get(
                    "current_price", 0.0
                )
                inv_val += inv["quantity"] * price
        partners_position_usd += bal_usd + inv_val

    cash_diff = owner_cash - partners_position_usd
    cash_status = "✅ Balanced" if cash_diff >= 0 else "🔴 Unbalanced"

    # ---------- Build stock reconciliation block (by item) ----------
    stock_lines = ["Item               Owner     Partners     Diff"]
    stock_lines.append("────────────────────────────────────────")
    for name, oq, pq, dq, ov, pv, dv in rows:
        diff_str = (
            f"{dq:+} pcs" if dq else "—"
        )  # show +/- or em-dash when zero
        stock_lines.append(
            f"{name:<16} {oq:>6} pcs   {pq:>6} pcs   {diff_str:>6}"
        )

    stock_lines.append("────────────────────────────────────────")
    stock_lines.append(
        f"Total             {grand_owner_qty:>6} pcs   {grand_partner_qty:>6} pcs   "
        f"{diff_qty_total:+6} pcs"
    )
    stock_lines.append(f"Status: {stock_status}")

    # ---------- Assemble final message ----------
    msg = (
        "📊 *Owner Overview*\n"
        "────────────────────────────────────────\n"
        f"🏦 POT Balance:          ${pot_balance:,.2f}\n"
        f"🏪 Stores Inventory:     ${store_inventory_val:,.2f}\n"
        "────────────────────────────────────────\n"
        f"💵 Owner Cash:           ${owner_cash:,.2f}\n"
        f"🤝 Partners Position:    ${partners_position_usd:,.2f}\n"
        "────────────────────────────────────────\n"
        f"⚖️ Cash Reconciliation:  {cash_status}"
        f"  ({cash_diff:+,.2f})\n\n"
        "📦 *Stock Reconciliation (by item)*\n"
        "────────────────────────────────────────\n"
        + "\n".join(stock_lines)
        + "\n────────────────────────────────────────"
    )

    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back", callback_data="owner_menu")]]
    )
    await update.callback_query.edit_message_text(
        msg, reply_markup=kb, parse_mode="Markdown"
    )

# ───────────────────────────────────────────
#   ...  (Set Market Prices & Adjust POT code
#        remains identical to the previous file)
# ───────────────────────────────────────────

# Register handlers (unchanged)
def register_owner_handlers(app):
    app.add_handler(
        CallbackQueryHandler(show_owner_menu, pattern="^owner_menu$")
    )
    app.add_handler(
        CallbackQueryHandler(show_owner_overview, pattern="^owner_overview$")
    )
    app.add_handler(
        CallbackQueryHandler(set_market_prices, pattern="^owner_set_prices$")
    )
    app.add_handler(
        CallbackQueryHandler(adjust_pot_balance, pattern="^owner_adjust_pot$")
    )

    # conversation flows (same as before) …
    #  price_conv and pot_conv adders stay here