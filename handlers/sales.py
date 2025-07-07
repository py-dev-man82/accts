# handlers/sales.py

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)
from datetime import datetime
from tinydb import Query

from handlers.utils import require_unlock
from secure_db import secure_db

# Conversation state constants
(
    S_CUST_SELECT,      # Add flow: customer select
    S_STORE_SELECT,     # Add flow: store select
    S_ITEM_QTY,         # Add flow: item/qty input
    S_PRICE,            # Add flow: price input
    S_FEE,              # Add flow: handling fee input
    S_NOTE,             # Add flow: note input
    S_CONFIRM,          # Add flow: confirm

    S_EDIT_SELECT,      # Edit flow: customer select
    S_EDIT_TIME,        # 🆕 Edit flow: time filter
    S_EDIT_PAGE,        # 🆕 Edit flow: paginated sales list
    S_EDIT_FIELD,       # Edit flow: field select
    S_EDIT_NEWVAL,      # Edit flow: new value input
    S_EDIT_CONFIRM,     # Edit flow: confirm

    S_DELETE_SELECT,    # Delete flow: customer select
    S_DELETE_CONFIRM,   # Delete flow: confirm delete

    S_VIEW_CUSTOMER,    # View flow: customer select
    S_VIEW_TIME,        # View flow: time filter
    S_VIEW_PAGE         # View flow: paginated sales list
) = range(18)


# ----------------- Sales Menu -------------------
async def show_sales_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Sale",    callback_data="add_sale")],
            [InlineKeyboardButton("👀 View Sales",  callback_data="view_sales")],
            [InlineKeyboardButton("✏️ Edit Sale",   callback_data="edit_sale")],
            [InlineKeyboardButton("🗑️ Remove Sale", callback_data="remove_sale")],
            [InlineKeyboardButton("🔙 Main Menu",   callback_data="main_menu")],
        ])
        await update.callback_query.edit_message_text(
            "Sales: choose an action", reply_markup=kb
        )

# ----------------- Add Sale Flow -------------------
@require_unlock
async def add_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all('customers')
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"sale_cust_{c.doc_id}") for c in customers]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return S_CUST_SELECT

async def get_sale_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split('_')[-1])
    context.user_data['sale_customer'] = cid
    stores = secure_db.all('stores')
    if not stores:
        await update.callback_query.edit_message_text(
            "No stores found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"sale_store_{s.doc_id}") for s in stores]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select store:", reply_markup=kb)
    return S_STORE_SELECT

async def get_sale_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data['sale_store'] = sid

    # Show store inventory
    Inventory = Query()
    inventory_items = secure_db.table('store_inventory').search(Inventory.store_id == sid)
    if inventory_items:
        inventory_lines = [f"• Item {r['item_id']}: {r['quantity']} units" for r in inventory_items]
        inventory_text = "\n".join(inventory_lines)
    else:
        inventory_text = "No inventory found for this store."

    await update.callback_query.edit_message_text(
        f"📦 Store Inventory:\n{inventory_text}\n\nEnter item_id,quantity (e.g. 7,3):"
    )
    return S_ITEM_QTY

async def get_sale_item_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        item_id, qty = map(int, text.split(','))
    except:
        await update.message.reply_text("❌ Invalid format. Use item_id,quantity (e.g. 7,3):")
        return S_ITEM_QTY

    # Validate stock availability
    sid = context.user_data['sale_store']
    Inventory = Query()
    item_record = secure_db.table('store_inventory').get((Inventory.store_id == sid) & (Inventory.item_id == item_id))
    if not item_record or item_record['quantity'] < qty:
        available = item_record['quantity'] if item_record else 0
        await update.message.reply_text(
            f"❌ Not enough stock for Item {item_id}.\nAvailable: {available} units.\nEnter a new item_id,quantity:"
        )
        return S_ITEM_QTY

    context.user_data['sale_item'] = item_id
    context.user_data['sale_qty'] = qty
    await update.message.reply_text("Enter unit price in store currency:")
    return S_PRICE

async def get_sale_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        price = float(text)
    except:
        await update.message.reply_text("❌ Invalid price. Enter a number:")
        return S_PRICE
    context.user_data['sale_price'] = price
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="fee_skip")]])
    await update.message.reply_text("Enter handling fee amount (or press Skip):", reply_markup=kb)
    return S_FEE

async def get_sale_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "fee_skip":
        await update.callback_query.answer()
        context.user_data['sale_fee'] = 0.0
    else:
        try:
            fee = float(update.message.text.strip())
            assert fee >= 0
            context.user_data['sale_fee'] = fee
        except:
            await update.message.reply_text("❌ Invalid fee. Enter a number or press Skip:")
            return S_FEE
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="note_skip")]])
    await update.message.reply_text("Enter an optional note for this sale (or press Skip):", reply_markup=kb)
    return S_NOTE

async def get_sale_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "note_skip":
        await update.callback_query.answer()
        context.user_data['sale_note'] = ""
    else:
        context.user_data['sale_note'] = update.message.text.strip()

    # Show confirmation summary
    cust_id = context.user_data['sale_customer']
    store_id = context.user_data['sale_store']
    customer = secure_db.table('customers').get(doc_id=cust_id)
    store = secure_db.table('stores').get(doc_id=store_id)
    item = context.user_data['sale_item']
    qty = context.user_data['sale_qty']
    price = context.user_data['sale_price']
    fee = context.user_data['sale_fee']
    note = context.user_data['sale_note'] or "—"
    total = qty * price

    summary = (
        f"✅ Confirm Sale\n"
        f"────────────────────────\n"
        f"Customer: {customer['name']} ({customer['currency']})\n"
        f"Store: {store['name']} ({store['currency']})\n"
        f"Item: {item}\n"
        f"Quantity: {qty}\n"
        f"Unit Price: {price:.2f} {store['currency']}\n"
        f"Total: {total:.2f} {store['currency']}\n"
        f"Handling Fee: {fee:.2f} {store['currency']}\n"
        f"Note: {note}\n"
        f"────────────────────────\n"
        f"Confirm?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="sale_yes"), InlineKeyboardButton("❌ No", callback_data="sale_no")]
    ])
    await update.message.reply_text(summary, reply_markup=kb)
    return S_CONFIRM

@require_unlock
async def confirm_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "sale_yes":
        # Record sale
        sale_data = {
            'customer_id': context.user_data['sale_customer'],
            'store_id': context.user_data['sale_store'],
            'item_id': context.user_data['sale_item'],
            'quantity': context.user_data['sale_qty'],
            'unit_price': context.user_data['sale_price'],
            'handling_fee': context.user_data['sale_fee'],
            'note': context.user_data['sale_note'],
            'currency': secure_db.table('stores').get(doc_id=context.user_data['sale_store'])['currency'],
            'timestamp': datetime.utcnow().isoformat()
        }
        secure_db.insert('sales', sale_data)

        # Deduct inventory
        Inventory = Query()
        item_record = secure_db.table('store_inventory').get(
            (Inventory.store_id == context.user_data['sale_store']) &
            (Inventory.item_id == context.user_data['sale_item'])
        )
        if item_record:
            new_qty = item_record['quantity'] - context.user_data['sale_qty']
            secure_db.update('store_inventory', {'quantity': new_qty}, [item_record.doc_id])

        # Credit handling fee to store if entered
        if context.user_data['sale_fee'] > 0:
            secure_db.insert('store_payments', {
                'store_id': context.user_data['sale_store'],
                'amount': context.user_data['sale_fee'],
                'currency': sale_data['currency'],
                'note': f"Handling fee for Customer Sale",
                'timestamp': datetime.utcnow().isoformat()
            })

        await update.callback_query.edit_message_text(
            "✅ Sale recorded.\n🏷️ Inventory updated.\n💸 Handling fee credited to store (if entered).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
    else:
        await show_sales_menu(update, context)
    return ConversationHandler.END

# ----------------- Edit Sale Flow -------------------
@require_unlock
async def edit_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all('customers')
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END

    # Show customer buttons
    buttons = [
        InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"edit_cust_{c.doc_id}")
        for c in customers
    ]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer to edit sales:", reply_markup=kb)
    return S_EDIT_SELECT


async def get_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = update.callback_query.data

    if data == "edit_time_back":
        return await edit_sale(update, context)  # Back to customer selection

    cid = int(data.split('_')[-1])
    context.user_data['edit_customer_id'] = cid

    # Prompt for time filter
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 Months", callback_data="edit_time_3m")],
        [InlineKeyboardButton("📅 Last 6 Months", callback_data="edit_time_6m")],
        [InlineKeyboardButton("📅 All Time", callback_data="edit_time_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="edit_sale")]
    ])
    await update.callback_query.edit_message_text("Select time period:", reply_markup=kb)
    return S_EDIT_TIME


async def get_edit_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    time_filter = update.callback_query.data.split('_')[-1]
    context.user_data['edit_time_filter'] = time_filter
    context.user_data['edit_page'] = 1
    return await send_edit_page(update, context)


async def send_edit_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = context.user_data['edit_customer_id']
    time_filter = context.user_data['edit_time_filter']
    page = context.user_data['edit_page']
    page_size = 20

    all_sales = [r for r in secure_db.all('sales') if r['customer_id'] == cid]

    if time_filter == "3m":
        cutoff = datetime.utcnow().timestamp() - (90 * 86400)
        all_sales = [r for r in all_sales if datetime.fromisoformat(r['timestamp']).timestamp() >= cutoff]
    elif time_filter == "6m":
        cutoff = datetime.utcnow().timestamp() - (180 * 86400)
        all_sales = [r for r in all_sales if datetime.fromisoformat(r['timestamp']).timestamp() >= cutoff]

    total_pages = max(1, (len(all_sales) + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    sales_chunk = all_sales[start:end]

    if not sales_chunk:
        await update.callback_query.edit_message_text(
            "No sales found for this customer in the selected period.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="edit_sale")]])
        )
        return ConversationHandler.END

    lines = [
        f"• [{r.doc_id}] Store:{r['store_id']} Item:{r['item_id']} "
        f"x{r['quantity']} @ {r['unit_price']} = {r['quantity'] * r['unit_price']:.2f} {r['currency']}"
        for r in sales_chunk
    ]
    text = f"✏️ Edit Sales (Page {page}/{total_pages}):\n" + "\n".join(lines)

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data="edit_prev"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("➡️ Next", callback_data="edit_next"))
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="edit_time_back"))
    kb = InlineKeyboardMarkup([buttons])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return S_EDIT_PAGE


async def handle_edit_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    action = update.callback_query.data
    if action == "edit_prev":
        context.user_data['edit_page'] -= 1
    elif action == "edit_next":
        context.user_data['edit_page'] += 1
    elif action == "edit_time_back":
        return await get_edit_customer(update, context)
    return await send_edit_page(update, context)

# ----------------- Delete Sale Flow -------------------
@require_unlock
async def delete_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all('customers')
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"del_cust_{c.doc_id}") for c in customers]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return S_DELETE_SELECT

async def get_delete_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split('_')[-1])
    context.user_data['delete_customer_id'] = cid

    # Fetch only this customer's sales
    rows = [r for r in secure_db.all('sales') if r['customer_id'] == cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No sales found for this customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(
        f"[{r.doc_id}] Store:{r['store_id']} Item:{r['item_id']} x{r['quantity']}",
        callback_data=f"del_sale_{r.doc_id}"
    ) for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+1] for i in range(0, len(buttons), 1)])
    await update.callback_query.edit_message_text("Select sale to delete:", reply_markup=kb)
    return S_DELETE_CONFIRM

async def confirm_delete_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split('_')[-1])
    sale = secure_db.table('sales').get(doc_id=sid)
    if not sale:
        await show_sales_menu(update, context)
        return ConversationHandler.END
    context.user_data['delete_sale'] = sale
    context.user_data['delete_sale_id'] = sid

    # Show confirmation summary
    summary = (
        f"⚠️ Confirm Deletion\n"
        f"────────────────────────\n"
        f"Sale #{sid} Details:\n"
        f"Customer: {sale['customer_id']}\n"
        f"Store: {sale['store_id']}\n"
        f"Item: {sale['item_id']}\n"
        f"Quantity: {sale['quantity']}\n"
        f"Unit Price: {sale['unit_price']:.2f} {sale['currency']}\n"
        f"Handling Fee: {sale.get('handling_fee', 0):.2f} {sale['currency']}\n"
        f"────────────────────────\n"
        f"This will:\n"
        f"• Restore {sale['quantity']} units to store inventory.\n"
        f"• Reverse handling fee payment (if any).\n"
        f"────────────────────────\n"
        f"Are you sure you want to delete this sale?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, delete", callback_data="del_conf_yes")],
        [InlineKeyboardButton("❌ No, cancel", callback_data="del_conf_no")]
    ])
    await update.callback_query.edit_message_text(summary, reply_markup=kb)
    return S_DELETE_CONFIRM

async def perform_delete_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "del_conf_yes":
        sale = context.user_data['delete_sale']
        sid = context.user_data['delete_sale_id']

        # Restore inventory
        Inventory = Query()
        item_rec = secure_db.table('store_inventory').get(
            (Inventory.store_id == sale['store_id']) & (Inventory.item_id == sale['item_id'])
        )
        if item_rec:
            secure_db.update('store_inventory', {'quantity': item_rec['quantity'] + sale['quantity']}, [item_rec.doc_id])

        # Reverse handling fee if applied
        if sale.get('handling_fee', 0) > 0:
            secure_db.insert('store_payments', {
                'store_id': sale['store_id'],
                'amount': -sale['handling_fee'],
                'currency': sale['currency'],
                'note': f"Reversal of handling fee for deleted Sale #{sid}",
                'timestamp': datetime.utcnow().isoformat()
            })

        # Delete sale
        secure_db.remove('sales', [sid])

        await update.callback_query.edit_message_text(
            f"✅ Sale #{sid} deleted.\n🏷️ Inventory restored.\n💸 Handling fee reversed (if any).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
    else:
        await show_sales_menu(update, context)
    return ConversationHandler.END

# ----------------- View Sales Flow -------------------
@require_unlock
async def view_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all('customers')
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END

    # Show customer buttons
    buttons = [
        InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"view_cust_{c.doc_id}")
        for c in customers
    ]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer to view sales:", reply_markup=kb)
    return S_VIEW_CUSTOMER


async def get_view_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = update.callback_query.data

    if data == "view_time_back":
        return await view_sales(update, context)  # Back to customer selection

    cid = int(data.split('_')[-1])
    context.user_data['view_customer_id'] = cid

    # Prompt for time filter
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 Months", callback_data="view_time_3m")],
        [InlineKeyboardButton("📅 Last 6 Months", callback_data="view_time_6m")],
        [InlineKeyboardButton("📅 All Time", callback_data="view_time_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="view_sales")]
    ])
    await update.callback_query.edit_message_text("Select time period:", reply_markup=kb)
    return S_VIEW_TIME


async def get_view_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    time_filter = update.callback_query.data.split('_')[-1]
    context.user_data['view_time_filter'] = time_filter
    context.user_data['view_page'] = 1
    return await send_sales_page(update, context)


async def send_sales_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = context.user_data['view_customer_id']
    time_filter = context.user_data['view_time_filter']
    page = context.user_data['view_page']
    page_size = 20

    all_sales = [r for r in secure_db.all('sales') if r['customer_id'] == cid]

    if time_filter == "3m":
        cutoff = datetime.utcnow().timestamp() - (90 * 86400)
        all_sales = [r for r in all_sales if datetime.fromisoformat(r['timestamp']).timestamp() >= cutoff]
    elif time_filter == "6m":
        cutoff = datetime.utcnow().timestamp() - (180 * 86400)
        all_sales = [r for r in all_sales if datetime.fromisoformat(r['timestamp']).timestamp() >= cutoff]

    total_pages = max(1, (len(all_sales) + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    sales_chunk = all_sales[start:end]

    if not sales_chunk:
        await update.callback_query.edit_message_text(
            "No sales found for this customer in the selected period.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="view_sales")]])
        )
        return ConversationHandler.END

    lines = [
        f"• [{r.doc_id}] Store:{r['store_id']} Item:{r['item_id']} "
        f"x{r['quantity']} @ {r['unit_price']} = {r['quantity'] * r['unit_price']:.2f} {r['currency']}"
        for r in sales_chunk
    ]
    text = f"📄 Sales (Page {page}/{total_pages}):\n" + "\n".join(lines)

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data="view_prev"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("➡️ Next", callback_data="view_next"))
    buttons.append(InlineKeyboardButton("🔙 Back", callback_data="view_time_back"))
    kb = InlineKeyboardMarkup([buttons])
    await update.callback_query.edit_message_text(text, reply_markup=kb)
    return S_VIEW_PAGE


async def handle_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    action = update.callback_query.data
    if action == "view_prev":
        context.user_data['view_page'] -= 1
    elif action == "view_next":
        context.user_data['view_page'] += 1
    elif action == "view_time_back":
        return await get_view_customer(update, context)
    return await send_sales_page(update, context)

# ----------------- Add Sale Flow -----------------
add_conv = ConversationHandler(
    entry_points=[
        CommandHandler("add_sale", add_sale),
        CallbackQueryHandler(add_sale, pattern="^add_sale$")
    ],
    states={
        S_CUST_SELECT: [
            CallbackQueryHandler(get_sale_customer, pattern="^sale_cust_")
        ],
        S_STORE_SELECT: [
            CallbackQueryHandler(get_sale_store, pattern="^sale_store_")
        ],
        S_ITEM_QTY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_item_qty)
        ],
        S_PRICE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_price)
        ],
        S_FEE: [
            CallbackQueryHandler(get_sale_fee, pattern="^fee_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_fee)
        ],
        S_NOTE: [
            CallbackQueryHandler(get_sale_note, pattern="^note_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_note)
        ],
        S_CONFIRM: [
            CallbackQueryHandler(confirm_sale, pattern="^sale_")
        ]
    },
    fallbacks=[CommandHandler("cancel", show_sales_menu)],
    per_message=False
)
# ----------------- Edit Sale: Select Sale -------------------
async def get_edit_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data['edit_sale_id'] = sid

    # Prompt to select field to edit
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Store", callback_data="edit_field_store")],
        [InlineKeyboardButton("Item & Quantity", callback_data="edit_field_itemqty")],
        [InlineKeyboardButton("Unit Price", callback_data="edit_field_price")],
        [InlineKeyboardButton("Handling Fee", callback_data="edit_field_fee")],
        [InlineKeyboardButton("Note", callback_data="edit_field_note")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="edit_sale")]
    ])
    await update.callback_query.edit_message_text("Select field to edit:", reply_markup=kb)
    return S_EDIT_FIELD


# ----------------- Edit Sale: Handle Field Selection -------------------
async def get_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    field = update.callback_query.data.split('_')[-1]
    context.user_data['edit_field'] = field

    if field == "store":
        stores = secure_db.all('stores')
        buttons = [
            InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"edit_new_store_{s.doc_id}")
            for s in stores
        ]
        kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
        await update.callback_query.edit_message_text("Select new store:", reply_markup=kb)

    elif field == "itemqty":
        await update.callback_query.edit_message_text("Enter new item_id,quantity (e.g. 5,10):")

    elif field == "price":
        await update.callback_query.edit_message_text("Enter new unit price:")

    elif field == "fee":
        await update.callback_query.edit_message_text("Enter new handling fee (or 0 for none):")

    elif field == "note":
        await update.callback_query.edit_message_text("Enter new note (or type '-' for none):")

    else:
        await update.callback_query.edit_message_text("Invalid field selected. Returning to menu...")
        return await edit_sale(update, context)

    return S_EDIT_NEWVAL
# ----------------- Edit Sale: Save New Value -------------------
async def save_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = context.user_data['edit_sale_id']
    field = context.user_data['edit_field']
    new_value = update.message.text.strip()
    context.user_data['new_value'] = new_value

    # Build confirmation message
    summary = (
        f"✅ Confirm Edit\n"
        f"────────────────────────────\n"
        f"Field: {field.title()}\n"
        f"New Value: {new_value}\n"
        f"────────────────────────────\n"
        f"Apply this change?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="edit_conf_yes")],
        [InlineKeyboardButton("❌ No", callback_data="edit_conf_no")]
    ])
    await update.message.reply_text(summary, reply_markup=kb)
    return S_EDIT_CONFIRM
# ----------------- Edit Sale: Confirm Edit -------------------
async def confirm_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "edit_conf_yes":
        sid = context.user_data['edit_sale_id']
        field = context.user_data['edit_field']
        new_value = context.user_data['new_value']

        # Apply changes to the database
        if field == "store":
            secure_db.update('sales', {'store_id': int(new_value)}, [sid])

        elif field == "itemqty":
            item_id, qty = map(int, new_value.split(','))
            secure_db.update('sales', {'item_id': item_id, 'quantity': qty}, [sid])

        elif field == "price":
            secure_db.update('sales', {'unit_price': float(new_value)}, [sid])

        elif field == "fee":
            secure_db.update('sales', {'handling_fee': float(new_value)}, [sid])

        elif field == "note":
            secure_db.update('sales', {'note': new_value}, [sid])

        await update.callback_query.edit_message_text(
            "✅ Sale updated successfully.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
    else:
        # User selected "No" - go back to the sales menu
        await edit_sale(update, context)

    return ConversationHandler.END

# ----------------- Register Handlers -------------------
def register_sales_handlers(app):
    app.add_handler(CallbackQueryHandler(show_sales_menu, pattern="^sales_menu$"))

    # ----------------- Add Sale -----------------
    app.add_handler(add_conv)

    # ----------------- Edit Sale -----------------
    edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_sale, pattern="^edit_sale$")
        ],
        states={
            S_EDIT_SELECT: [
                CallbackQueryHandler(get_edit_customer, pattern="^edit_cust_"),
                CallbackQueryHandler(edit_sale, pattern="^edit_sale$")  # Back button
            ],
            S_EDIT_TIME: [
                CallbackQueryHandler(get_edit_time, pattern="^edit_time_"),
                CallbackQueryHandler(edit_sale, pattern="^edit_sale$")  # Back button
            ],
            S_EDIT_PAGE: [
                CallbackQueryHandler(handle_edit_pagination, pattern="^edit_(prev|next)$"),
                CallbackQueryHandler(get_edit_customer, pattern="^edit_time_back$")
            ],
            S_EDIT_FIELD: [
                CallbackQueryHandler(get_edit_sale, pattern="^edit_sale_")  # 🆕 Fixed handler
            ],
            S_EDIT_NEWVAL: [
                CallbackQueryHandler(get_edit_field, pattern="^edit_field_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit)
            ],
            S_EDIT_CONFIRM: [
                CallbackQueryHandler(confirm_edit, pattern="^edit_conf_")
            ]
        },
        fallbacks=[CommandHandler("cancel", show_sales_menu)],
        per_message=False
    )
    app.add_handler(edit_conv)

    # ----------------- Delete Sale -----------------
    app.add_handler(delete_conv)

    # ----------------- View Sales -----------------
    app.add_handler(view_conv)
