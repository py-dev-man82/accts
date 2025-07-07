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
    S_CUST_SELECT,
    S_STORE_SELECT,
    S_ITEM_QTY,
    S_PRICE,
    S_FEE,
    S_NOTE,
    S_CONFIRM,
    S_EDIT_SELECT,
    S_EDIT_FIELD,
    S_EDIT_NEWVAL,
    S_EDIT_CONFIRM,
    S_DELETE_SELECT,
    S_DELETE_CONFIRM,
) = range(13)

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
    sales = secure_db.all('sales')
    if not sales:
        await update.callback_query.edit_message_text(
            "No sales to edit.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(
        f"[{s.doc_id}] Cust:{s['customer_id']} Store:{s['store_id']} Item:{s['item_id']} x{s['quantity']}",
        callback_data=f"edit_sale_{s.doc_id}"
    ) for s in sales]
    kb = InlineKeyboardMarkup([buttons[i:i+1] for i in range(0, len(buttons), 1)])
    await update.callback_query.edit_message_text("Select sale to edit:", reply_markup=kb)
    return S_EDIT_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split('_')[-1])
    sale = secure_db.table('sales').get(doc_id=sid)
    if not sale:
        await show_sales_menu(update, context)
        return ConversationHandler.END
    context.user_data['edit_sale'] = sale
    context.user_data['edit_sale_id'] = sid

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Customer", callback_data="edit_field_customer")],
        [InlineKeyboardButton("Store", callback_data="edit_field_store")],
        [InlineKeyboardButton("Item & Quantity", callback_data="edit_field_itemqty")],
        [InlineKeyboardButton("Unit Price", callback_data="edit_field_price")],
        [InlineKeyboardButton("Handling Fee", callback_data="edit_field_fee")],
        [InlineKeyboardButton("Note", callback_data="edit_field_note")],
        [InlineKeyboardButton("❌ Cancel", callback_data="edit_field_cancel")]
    ])
    await update.callback_query.edit_message_text("Select field to edit:", reply_markup=kb)
    return S_EDIT_FIELD

async def get_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    field = update.callback_query.data.split('_')[-1]
    context.user_data['edit_field'] = field
    if field == "customer":
        customers = secure_db.all('customers')
        buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})", callback_data=f"edit_new_customer_{c.doc_id}") for c in customers]
        kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
        await update.callback_query.edit_message_text("Select new customer:", reply_markup=kb)
    elif field == "store":
        stores = secure_db.all('stores')
        buttons = [InlineKeyboardButton(f"{s['name']} ({s['currency']})", callback_data=f"edit_new_store_{s.doc_id}") for s in stores]
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
        await show_sales_menu(update, context)
        return ConversationHandler.END
    return S_EDIT_NEWVAL

async def save_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = context.user_data['edit_sale_id']
    field = context.user_data['edit_field']
    sale = context.user_data['edit_sale']
    old_value = sale.get(field)
    new_value = None

    # Handle new value based on field
    if field in ["customer", "store"]:
        new_value = int(update.callback_query.data.split('_')[-1])
    elif field == "itemqty":
        try:
            item_id, qty = map(int, update.message.text.strip().split(','))
            new_value = (item_id, qty)
        except:
            await update.message.reply_text("Invalid format. Use item_id,quantity (e.g. 5,10):")
            return S_EDIT_NEWVAL
    elif field in ["price", "fee"]:
        try:
            new_value = float(update.message.text.strip())
        except:
            await update.message.reply_text("Invalid number. Try again:")
            return S_EDIT_NEWVAL
    elif field == "note":
        new_value = "" if update.message.text.strip() == "-" else update.message.text.strip()

    # Show confirmation screen
    summary = (
        f"✅ Confirm Edit\n"
        f"────────────────────────\n"
        f"Field: {field.title()}\n"
        f"Old Value: {old_value}\n"
        f"New Value: {new_value}\n"
        f"────────────────────────\n"
        f"Apply this change?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="edit_conf_yes"), InlineKeyboardButton("❌ No", callback_data="edit_conf_no")]
    ])
    context.user_data['new_value'] = new_value
    await update.message.reply_text(summary, reply_markup=kb)
    return S_EDIT_CONFIRM

async def confirm_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "edit_conf_yes":
        sid = context.user_data['edit_sale_id']
        field = context.user_data['edit_field']
        sale = context.user_data['edit_sale']
        new_value = context.user_data['new_value']

        # Apply changes and adjust inventory/fee if needed
        if field == "customer":
            secure_db.update('sales', {'customer_id': new_value}, [sid])
        elif field == "store":
            secure_db.update('sales', {'store_id': new_value}, [sid])
        elif field == "itemqty":
            old_qty = sale['quantity']
            item_id, qty = new_value
            secure_db.update('sales', {'item_id': item_id, 'quantity': qty}, [sid])
            # Adjust inventory
            diff = qty - old_qty
            Inventory = Query()
            item_rec = secure_db.table('store_inventory').get(
                (Inventory.store_id == sale['store_id']) & (Inventory.item_id == item_id)
            )
            if item_rec:
                secure_db.update('store_inventory', {'quantity': item_rec['quantity'] - diff}, [item_rec.doc_id])
        elif field == "price":
            secure_db.update('sales', {'unit_price': new_value}, [sid])
        elif field == "fee":
            old_fee = sale.get('handling_fee', 0)
            secure_db.update('sales', {'handling_fee': new_value}, [sid])
            # Adjust store payment for fee difference
            fee_diff = new_value - old_fee
            if fee_diff != 0:
                secure_db.insert('store_payments', {
                    'store_id': sale['store_id'],
                    'amount': fee_diff,
                    'currency': sale['currency'],
                    'note': f"Adjustment for handling fee on Sale #{sid}",
                    'timestamp': datetime.utcnow().isoformat()
                })
        elif field == "note":
            secure_db.update('sales', {'note': new_value}, [sid])

        await update.callback_query.edit_message_text(
            "✅ Sale updated successfully.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
    else:
        await show_sales_menu(update, context)
    return ConversationHandler.END

# ----------------- Delete Sale Flow -------------------
@require_unlock
async def delete_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sales = secure_db.all('sales')
    if not sales:
        await update.callback_query.edit_message_text(
            "No sales to delete.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(
        f"[{s.doc_id}] Cust:{s['customer_id']} Store:{s['store_id']} Item:{s['item_id']} x{s['quantity']}",
        callback_data=f"del_sale_{s.doc_id}"
    ) for s in sales]
    kb = InlineKeyboardMarkup([buttons[i:i+1] for i in range(0, len(buttons), 1)])
    await update.callback_query.edit_message_text("Select sale to delete:", reply_markup=kb)
    return S_DELETE_SELECT

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
async def view_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = secure_db.all('sales')
    if not rows:
        text = "No sales found."
    else:
        lines = []
        for r in rows:
            total = r['quantity'] * r['unit_price']
            lines.append(
                f"• [{r.doc_id}] cust:{r['customer_id']} store:{r['store_id']} "
                f"item:{r['item_id']} x{r['quantity']} @ {r['unit_price']} = {total}"
            )
        text = "Sales:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# ----------------- Register Handlers -------------------
def register_sales_handlers(app):
    app.add_handler(CallbackQueryHandler(show_sales_menu, pattern="^sales_menu$"))

    # Add Sale
    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_sale", add_sale),
            CallbackQueryHandler(add_sale, pattern="^add_sale$")
        ],
        states={
            S_CUST_SELECT:  [CallbackQueryHandler(get_sale_customer, pattern="^sale_cust_")],
            S_STORE_SELECT: [CallbackQueryHandler(get_sale_store, pattern="^sale_store_")],
            S_ITEM_QTY:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_item_qty)],
            S_PRICE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_price)],
            S_FEE:          [CallbackQueryHandler(get_sale_fee, pattern="^fee_skip$"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_fee)],
            S_NOTE:         [CallbackQueryHandler(get_sale_note, pattern="^note_skip$"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_note)],
            S_CONFIRM:      [CallbackQueryHandler(confirm_sale, pattern="^sale_")]
        },
        fallbacks=[CommandHandler("cancel", show_sales_menu)],
        per_message=False
    )
    app.add_handler(add_conv)

    # Edit Sale
    edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_sale, pattern="^edit_sale$")],
        states={
            S_EDIT_SELECT:  [CallbackQueryHandler(get_edit_selection, pattern="^edit_sale_")],
            S_EDIT_FIELD:   [CallbackQueryHandler(get_edit_field, pattern="^edit_field_")],
            S_EDIT_NEWVAL:  [CallbackQueryHandler(save_edit, pattern="^edit_new_"),
                             MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit)],
            S_EDIT_CONFIRM: [CallbackQueryHandler(confirm_edit, pattern="^edit_conf_")]
        },
        fallbacks=[CommandHandler("cancel", show_sales_menu)],
        per_message=False
    )
    app.add_handler(edit_conv)

    # Delete Sale
    delete_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_sale, pattern="^remove_sale$")],
        states={
            S_DELETE_SELECT:  [CallbackQueryHandler(confirm_delete_sale, pattern="^del_sale_")],
            S_DELETE_CONFIRM: [CallbackQueryHandler(perform_delete_sale, pattern="^del_conf_")]
        },
        fallbacks=[CommandHandler("cancel", show_sales_menu)],
        per_message=False
    )
    app.add_handler(delete_conv)

    # View Sales
    app.add_handler(CallbackQueryHandler(view_sales, pattern="^view_sales$"))