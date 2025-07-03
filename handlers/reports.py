from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes
from datetime import datetime, date, timedelta
from tinydb import Query
from secure_db import secure_db

# State constants
(
    REP_SEL_CUST, REP_SHOW_CUST,
    REP_SEL_PART, REP_SHOW_PART,
    REP_SEL_STORE, REP_SHOW_STORE,
    REP_OWNER
) = range(7)

# --- Customer Reports ---
async def select_report_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = secure_db.all('customers')
    buttons = [[InlineKeyboardButton(r['name'], callback_data=f"rep_cust_{r.doc_id}")] for r in rows]
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data='back_main')])
    await update.callback_query.edit_message_text(
        "Select customer for report:", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return REP_SHOW_CUST

async def show_report_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = int(update.callback_query.data.split('_')[-1])
    today = date.today()
    week_ago = today - timedelta(days=7)
    Q = Query()
    sales = secure_db.search('customer_sales',
        (Q.customer_id == cid) &
        (Q.created_at.test(lambda d: week_ago <= datetime.fromisoformat(d).date() <= today))
    )
    pays = secure_db.search('customer_payments',
        (Q.customer_id == cid) &
        (Q.created_at.test(lambda d: week_ago <= datetime.fromisoformat(d).date() <= today))
    )
    total_sales = sum(s['qty'] * s['unit_price'] for s in sales)
    total_usd   = sum(p['usd_amount'] for p in pays)
    lines = [
        f"👤 Customer Report",
        f"📆 {week_ago} → {today}",
        "",
        "🛒 Sales:"
    ] + [
        f"- {s['created_at'][:10]} • Item {s['item_id']}×{s['qty']} @{s['unit_price']:.2f} → {s['qty']*s['unit_price']:.2f}"
        for s in sales
    ] + [f"→ Total Sales: {total_sales:.2f}", "", "💳 Payments:"] + [
        f"- {p['created_at'][:10]} • {p['local_amount']:.2f}-{p['fee']:.2f} → ${p['usd_amount']:.2f}"
        for p in pays
    ] + [f"→ Total USD: ${total_usd:.2f}"]
    await update.callback_query.edit_message_text("\n".join(lines))
    return MAIN_MENU

# --- Partner Reports ---
async def select_report_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = secure_db.all('partners')
    buttons = [[InlineKeyboardButton(r['name'], callback_data=f"rep_part_{r.doc_id}")] for r in rows]
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data='back_main')])
    await update.callback_query.edit_message_text(
        "Select partner for report:", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return REP_SHOW_PART

async def show_report_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = int(update.callback_query.data.split('_')[-1])
    today = date.today()
    week_ago = today - timedelta(days=7)
    Q = Query()
    inv = secure_db.search('partner_inventory', Query().partner_id == pid)
    sales = secure_db.search('customer_sales', Query().store_id == pid)  # assuming store==partner
    payouts = secure_db.search('partner_payouts',
        (Q.partner_id == pid) &
        (Q.created_at.test(lambda d: week_ago <= datetime.fromisoformat(d).date() <= today))
    )
    # Build lines...
    lines = [f"🤝 Partner Report", f"📆 {week_ago} → {today}", "", "📦 Inventory:"]
    lines += [f"- Item {r['item_id']}: {r['qty']} units" for r in inv]
    lines += ["", "🛒 Sales (customer sales via partner):"]
    lines += [f"- {s['created_at'][:10]} • Item {s['item_id']}×{s['qty']} → {s['qty']*s['unit_price']:.2f}"
              for s in sales]
    lines += ["", "💵 Payouts:"]
    lines += [f"- {p['created_at'][:10]} • ${p['amount_usd']:.2f}" for p in payouts]
    await update.callback_query.edit_message_text("\n".join(lines))
    return MAIN_MENU

# --- Store Reports ---
async def select_report_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = secure_db.all('stores')
    buttons = [[InlineKeyboardButton(r['name'], callback_data=f"rep_store_{r.doc_id}")] for r in rows]
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data='back_main')])
    await update.callback_query.edit_message_text(
        "Select store for report:", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return REP_SHOW_STORE

async def show_report_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split('_')[-1])
    today = date.today()
    week_ago = today - timedelta(days=7)
    Q = Query()
    inv = secure_db.search('store_inventory', Query().store_id == sid)
    fees = secure_db.search('store_handling_income',
        (Q.store_id == sid) &
        (Q.created_at.test(lambda d: week_ago <= datetime.fromisoformat(d).date() <= today))
    )
    lines = [f"🏬 Store Report", f"📆 {week_ago} → {today}", "", "📦 Inventory:"]
    lines += [f"- Item {r['item_id']}: {r['qty']} units" for r in inv]
    lines += ["", "💹 Handling Fees:"]
    lines += [f"- {f['created_at'][:10]} • Item {f['item_id']}×{f['qty']} @ {f['fee_per_unit']:.2f} → {f['total_fee']:.2f}"
              for f in fees]
    await update.callback_query.edit_message_text("\n".join(lines))
    return MAIN_MENU

# --- Owner (POT) Report ---
async def report_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    week_ago = today - timedelta(days=7)
    start = secure_db.all('pot')[-1]['current_balance']
    payments = sum(p['usd_amount'] for p in secure_db.all('customer_payments'))
    payouts  = sum(p['amount_usd'] for p in secure_db.all('partner_payouts'))
    balance  = start + payments - payouts
    lines = [
        f"🛡️ POT Report",
        f"📆 {week_ago} → {today}",
        "",
        f"Starting Balance: ${start:.2f}",
        f"All Payments:     ${payments:.2f}",
        f"All Payouts:      ${payouts:.2f}",
        f"Current Balance:  ${balance:.2f}"
    ]
    await update.callback_query.edit_message_text("\n".join(lines))
    return MAIN_MENU

def register_report_handlers(app):
    app.add_handler(CallbackQueryHandler(select_report_customer, pattern='^rep_cust_select$'))
    app.add_handler(CallbackQueryHandler(show_report_customer,   pattern='^rep_cust_\\d+$'))
    app.add_handler(CallbackQueryHandler(select_report_partner,  pattern='^rep_part_select$'))
    app.add_handler(CallbackQueryHandler(show_report_partner,    pattern='^rep_part_\\d+$'))
    app.add_handler(CallbackQueryHandler(select_report_store,    pattern='^rep_store_select$'))
    app.add_handler(CallbackQueryHandler(show_report_store,      pattern='^rep_store_\\d+$'))
    app.add_handler(CommandHandler('rep_owner', report_owner))
