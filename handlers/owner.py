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

# ────────────────────────────────────────────────
# Conversation-state constants
# ────────────────────────────────────────────────
(
    O_PRICE_SELECT,
    O_PRICE_INPUT,
    O_PRICE_CONFIRM,
    O_POT_ACTION,
    O_POT_INPUT,
    O_POT_NOTE,
    O_POT_CONFIRM,
) = range(7)

# ────────────────────────────────────────────────
# Self-healing schema
# ────────────────────────────────────────────────
def ensure_owner_schema() -> None:
    _ = secure_db.all("owner_adjustments")              # auto-create if needed
    for item in secure_db.all("items"):
        if "current_price" not in item:
            secure_db.update("items", {"current_price": 0.0}, [item.doc_id])
ensure_owner_schema()

# ════════════════════════════════════════════════
# Owner Main Menu
# ════════════════════════════════════════════════
async def show_owner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Overview",          callback_data="owner_overview")],
            [InlineKeyboardButton("💲 Set Market Prices", callback_data="owner_set_prices")],
            [InlineKeyboardButton("🏦 Adjust POT Balance",callback_data="owner_adjust_pot")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ]
    )
    await update.callback_query.edit_message_text("👑 Owner: choose an action", reply_markup=kb)

# ════════════════════════════════════════════════
# Overview (cash + per-item stock reconciliation)
# ════════════════════════════════════════════════
@require_unlock
async def show_owner_overview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    # ---- POT cash flows ------------------------------------------------
    pot_in  = sum(
        r.get("usd_amt", (r.get("local_amt",0)-r.get("fee_amt",0))/(r.get("fx_rate",1.0) or 1.0))
        for r in secure_db.all("customer_payments")
    )
    pot_out = sum(
        r.get("usd_amt", (r.get("local_amt",0)-r.get("fee_amt",0))/(r.get("fx_rate",1.0) or 1.0))
        for r in secure_db.all("partner_payouts")
    )
    adjustments = sum(r.get("amount",0.0) for r in secure_db.all("owner_adjustments"))
    pot_balance = pot_in - pot_out + adjustments

    # ---- Build owner & partner item maps --------------------------------
    owner_qty   = {}
    partner_qty = {}
    for s in secure_db.all("sales"):
        owner_qty[s["item_id"]] = owner_qty.get(s["item_id"],0) + s["quantity"]
    for inv in secure_db.all("partner_inventory"):
        partner_qty[inv["item_id"]] = partner_qty.get(inv["item_id"],0) + inv["quantity"]

    rows = []
    g_owner_q = g_partner_q = 0
    g_owner_v = g_partner_v = 0.0

    for it in secure_db.all("items"):
        iid, name, price = it.doc_id, it["name"], it.get("current_price",0.0)
        oq, pq = owner_qty.get(iid,0), partner_qty.get(iid,0)
        if oq==pq==0:
            continue
        dq  = oq-pq
        ov, pv, dv = oq*price, pq*price, dq*price
        rows.append((name,oq,pq,dq,ov,pv,dv))
        g_owner_q += oq; g_partner_q += pq
        g_owner_v += ov; g_partner_v += pv

    diff_q  = g_owner_q - g_partner_q
    diff_v  = g_owner_v - g_partner_v
    stock_ok= diff_q==0
    store_inventory_val = g_owner_v
    owner_cash = pot_balance + store_inventory_val

    # partner aggregate position (cash+inventory) -------------------------
    partners_pos = 0.0
    for p in secure_db.all("partners"):
        bal_usd = 0.0
        for s in secure_db.all("sales"):
            if s.get("partner_id")==p.doc_id:
                bal_usd += s["quantity"]*s["unit_price"]
        for out in secure_db.all("partner_payouts"):
            if out.get("partner_id")==p.doc_id:
                bal_usd -= out.get("usd_amt",(out.get("local_amt",0)-out.get("fee_amt",0))/(out.get("fx_rate",1.0) or 1.0))
        inv_val = sum(
            inv["quantity"]*secure_db.table("items").get(doc_id=inv["item_id"]).get("current_price",0.0)
            for inv in secure_db.all("partner_inventory") if inv["partner_id"]==p.doc_id
        )
        partners_pos += bal_usd + inv_val

    cash_diff  = owner_cash - partners_pos
    cash_ok    = cash_diff>=0

    # ---- Stock table pretty-print ---------------------------------------
    stock_lines = ["Item               Owner   Partners    Diff"]
    stock_lines.append("────────────────────────────────────────")
    for name,oq,pq,dq,ov,pv,dv in rows:
        diff_str = f"{dq:+} pcs" if dq else "—"
        stock_lines.append(f"{name:<16} {oq:>6}   {pq:>6}   {diff_str:>7}")
    stock_lines.append("────────────────────────────────────────")
    stock_lines.append(
        f"Total             {g_owner_q:>6}   {g_partner_q:>6}   {diff_q:+7} pcs\n"
        f"Status: {'✅ Balanced' if stock_ok else '⚠️ Unbalanced'}"
    )

    msg = (
        "📊 *Owner Overview*\n"
        "────────────────────────────────────────\n"
        f"🏦 POT Balance:          ${pot_balance:,.2f}\n"
        f"🏪 Stores Inventory:     ${store_inventory_val:,.2f}\n"
        "────────────────────────────────────────\n"
        f"💵 Owner Cash:           ${owner_cash:,.2f}\n"
        f"🤝 Partners Position:    ${partners_pos:,.2f}\n"
        "────────────────────────────────────────\n"
        f"⚖️ Cash Reconciliation:  {'✅ Balanced' if cash_ok else '🔴 Unbalanced'}"
        f" ({cash_diff:+,.2f})\n\n"
        "📦 *Stock Reconciliation (by item)*\n"
        "────────────────────────────────────────\n"
        + "\n".join(stock_lines)
        + "\n────────────────────────────────────────"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="owner_menu")]])
    await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")

# ════════════════════════════════════════════════
# Set Market Prices flow
# ════════════════════════════════════════════════
@require_unlock
async def set_market_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    items = secure_db.all("items")
    if not items:
        await update.callback_query.edit_message_text(
            "No items found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="owner_menu")]]))
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{it['name']} (${it.get('current_price',0):.2f})",
                             callback_data=f"price_item_{it.doc_id}")
        for it in items
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("📦 Select an item:", reply_markup=kb)
    return O_PRICE_SELECT

async def get_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    iid = int(update.callback_query.data.split("_")[-1])
    context.user_data["price_item_id"] = iid
    item = secure_db.table("items").get(doc_id=iid)
    context.user_data["price_item_name"] = item["name"]
    await update.callback_query.edit_message_text(
        f"{item['name']}\n─────────────\nCurrent: ${item.get('current_price',0):.2f}\n\n"
        "Enter new market price:")
    return O_PRICE_INPUT

async def confirm_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip()); assert price>0
    except:
        await update.message.reply_text("Positive number please:"); return O_PRICE_INPUT
    context.user_data["new_price"] = price
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes",callback_data="price_conf_yes"),
         InlineKeyboardButton("❌ Cancel",callback_data="price_conf_no")]
    ])
    await update.message.reply_text(
        f"Set *{context.user_data['price_item_name']}* price to ${price:.2f}?",
        reply_markup=kb, parse_mode="Markdown")
    return O_PRICE_CONFIRM

@require_unlock
async def save_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data=="price_conf_yes":
        secure_db.update("items",{"current_price":context.user_data["new_price"]},
                         [context.user_data["price_item_id"]])
        txt=f"✅ Updated to ${context.user_data['new_price']:.2f}."
    else:
        txt="❌ Cancelled."
    await update.callback_query.edit_message_text(
        txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="owner_menu")]]))
    return ConversationHandler.END

# ════════════════════════════════════════════════
# Adjust POT Balance flow
# ════════════════════════════════════════════════
@require_unlock
async def adjust_pot_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    pot_in  = sum(
        r.get("usd_amt",(r.get("local_amt",0)-r.get("fee_amt",0))/(r.get("fx_rate",1.0) or 1.0))
        for r in secure_db.all("customer_payments")
    )
    pot_out = sum(
        r.get("usd_amt",(r.get("local_amt",0)-r.get("fee_amt",0))/(r.get("fx_rate",1.0) or 1.0))
        for r in secure_db.all("partner_payouts")
    )
    adjustments=sum(r.get("amount",0.0) for r in secure_db.all("owner_adjustments"))
    pot_balance=pot_in-pot_out+adjustments

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Funds",callback_data="pot_add"),
         InlineKeyboardButton("➖ Subtract Funds",callback_data="pot_subtract")],
        [InlineKeyboardButton("✏️ Set Exact Balance",callback_data="pot_set")],
        [InlineKeyboardButton("🔙 Back",callback_data="owner_menu")],
    ])
    await update.callback_query.edit_message_text(
        f"🏦 Current POT Balance: ${pot_balance:,.2f}\n\nChoose:", reply_markup=kb)
    return O_POT_ACTION

async def get_pot_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["pot_action"]=update.callback_query.data  # pot_add|pot_subtract|pot_set
    prompt={"pot_add":"Enter amount to add:",
            "pot_subtract":"Enter amount to subtract:",
            "pot_set":"Enter new POT balance:"}[update.callback_query.data]
    await update.callback_query.edit_message_text(prompt)
    return O_POT_INPUT

async def get_pot_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: amt=float(update.message.text.strip())
    except: await update.message.reply_text("Number please:"); return O_POT_INPUT
    context.user_data["pot_amount"]=amt
    await update.message.reply_text("Optional note (or type 'skip'):")
    return O_POT_NOTE

async def confirm_pot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note=update.message.text.strip(); note="" if note.lower()=="skip" else note
    context.user_data["pot_note"]=note
    act=context.user_data["pot_action"]; amt=context.user_data["pot_amount"]
    txt={"pot_add":f"Add ${amt:,.2f}?",
         "pot_subtract":f"Subtract ${amt:,.2f}?",
         "pot_set":f"Set POT balance to ${amt:,.2f}?"}[act]
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes",callback_data="pot_conf_yes"),
                              InlineKeyboardButton("❌ Cancel",callback_data="pot_conf_no")]])
    await update.message.reply_text(f"{txt}\nNote: {note or '—'}", reply_markup=kb)
    return O_POT_CONFIRM

@require_unlock
async def save_pot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data!="pot_conf_yes":
        await update.callback_query.edit_message_text(
            "❌ Cancelled.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="owner_menu")]]))
        return ConversationHandler.END

    act= context.user_data["pot_action"]
    amt= context.user_data["pot_amount"]
    note=context.user_data["pot_note"]

    if act=="pot_set":
        # compute current pot then insert delta
        pot_now = sum(
            r.get("usd_amt",(r.get("local_amt",0)-r.get("fee_amt",0))/(r.get("fx_rate",1.0) or 1.0))
            for r in secure_db.all("customer_payments")
        ) - sum(
            r.get("usd_amt",(r.get("local_amt",0)-r.get("fee_amt",0))/(r.get("fx_rate",1.0) or 1.0))
            for r in secure_db.all("partner_payouts")
        ) + sum(r.get("amount",0.0) for r in secure_db.all("owner_adjustments"))
        delta = amt - pot_now
    else:
        delta = amt if act=="pot_add" else -amt

    secure_db.insert("owner_adjustments",
        {"amount":delta,"note":note,"timestamp":datetime.utcnow().isoformat()})

    msg = f"✅ POT adjusted by {delta:+,.2f}."
    await update.callback_query.edit_message_text(
        msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="owner_menu")]]))
    return ConversationHandler.END

# ════════════════════════════════════════════════
# Register owner handlers
# ════════════════════════════════════════════════
def register_owner_handlers(app):
    app.add_handler(CallbackQueryHandler(show_owner_menu,     pattern="^owner_menu$"))
    app.add_handler(CallbackQueryHandler(show_owner_overview, pattern="^owner_overview$"))
    app.add_handler(CallbackQueryHandler(set_market_prices,   pattern="^owner_set_prices$"))
    app.add_handler(CallbackQueryHandler(adjust_pot_balance,  pattern="^owner_adjust_pot$"))

    price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(get_price_input,pattern="^price_item_\\d+$")],
        states={
            O_PRICE_INPUT:[MessageHandler(filters.TEXT & ~filters.COMMAND,confirm_price)],
            O_PRICE_CONFIRM:[CallbackQueryHandler(save_price,pattern="^price_conf_")],
        }, fallbacks=[CommandHandler("cancel",show_owner_menu)], per_message=False)
    app.add_handler(price_conv)

    pot_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(get_pot_amount,pattern="^pot_(add|subtract|set)$")],
        states={
            O_POT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND,get_pot_note)],
            O_POT_NOTE:  [MessageHandler(filters.TEXT & ~filters.COMMAND,confirm_pot)],
            O_POT_CONFIRM:[CallbackQueryHandler(save_pot,pattern="^pot_conf_")],
        }, fallbacks=[CommandHandler("cancel",show_owner_menu)], per_message=False)
    app.add_handler(pot_conv)