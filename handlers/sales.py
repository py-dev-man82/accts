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

# State constants for the sales flow
(
    S_CUST_SELECT,
    S_STORE_SELECT,
    S_ITEM_QTY,
    S_PRICE,
    S_CONFIRM,
    S_VIEW,
    S_EDIT_SELECT,
    S_EDIT_FIELD,
    S_EDIT_NEWVAL,
    S_EDIT_CONFIRM,
    S_DELETE_SELECT,
    S_DELETE_CONFIRM,
) = range(12)

# --- Submenu for Sales Management ---
async def show_sales_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing sales submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Sale",    callback_data="add_sale")],
            [InlineKeyboardButton("👀 View Sales", callback_data="view_sales")],
            [InlineKeyboardButton("✏️ Edit Sale",  callback_data="edit_sale")],
            [InlineKeyboardButton("🗑️ Remove Sale",callback_data="remove_sale")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])
        await update.callback_query.edit_message_text(
            "Sales Management: choose an action", reply_markup=kb
        )

# --- Add Sale Flow ---
@require_unlock
async def add_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_sale")
    await update.callback_query.answer()
    # Select customer
    rows = secure_db.all('customers')
    buttons = [InlineKeyboardButton(f"{r['name']}", callback_data=f"sale_cust_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=kb)
    return S_CUST_SELECT

async def get_sale_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split('_')[-1])
    context.user_data['sale_customer'] = cid
    # Select store
    rows = secure_db.all('stores')
    buttons = [InlineKeyboardButton(f"{r['name']}", callback_data=f"sale_store_{r.doc_id}") for r in rows]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select store:", reply_markup=kb)
    return S_STORE_SELECT

async def get_sale_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data['sale_store'] = sid
    await update.callback_query.edit_message_text("Enter item_id,quantity (e.g. 1,3):")
    return S_ITEM_QTY

async def get_sale_item_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    logging.info("Received item_qty: %s", text)
    try:
        item_id, qty = map(int, text.split(','))
    except:
        await update.message.reply_text("Invalid format. Use item_id,quantity")
        return S_ITEM_QTY
    context.user_data['sale_item'] = item_id
    context.user_data['sale_qty'] = qty
    await update.message.reply_text("Enter unit price in store currency:")
    return S_PRICE

async def get_sale_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    logging.info("Received price: %s", text)
    try:
        price = float(text)
    except:
        await update.message.reply_text("Invalid price. Enter a number.")
        return S_PRICE
    context.user_data['sale_price'] = price
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data="sale_yes"),
        InlineKeyboardButton("❌ No",  callback_data="sale_no")
    ]])
    await update.message.reply_text(
        f"Confirm sale: customer {context.user_data['sale_customer']}, "
        f"store {context.user_data['sale_store']}, "
        f"item {context.user_data['sale_item']} x{context.user_data['sale_qty']} at {price}?",
        reply_markup=kb
    )
    return S_CONFIRM

@require_unlock
async def confirm_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'sale_yes':
        secure_db.insert('sales', {
            'customer_id': context.user_data['sale_customer'],
            'store_id':    context.user_data['sale_store'],
            'item_id':     context.user_data['sale_item'],
            'quantity':    context.user_data['sale_qty'],
            'unit_price':  context.user_data['sale_price'],
            'currency':    secure_db.table('stores').get(doc_id=context.user_data['sale_store'])['currency'],
            'timestamp':   datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            "✅ Sale recorded.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
    else:
        await show_sales_menu(update, context)
    return ConversationHandler.END

# --- View Sales Flow ---
async def view_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View sales")
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
                f"item:{r['item_id']} x{r['quantity']} @ {r['unit_price']} = {total}" )
        text = "Sales:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)

# --- Registration ---
def register_sales_handlers(app):
    app.add_handler(CallbackQueryHandler(show_sales_menu, pattern="^sales_menu$"))

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
            S_CONFIRM:      [CallbackQueryHandler(confirm_sale, pattern="^sale_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_sale)],
        per_message=False
    )
    app.add_handler(add_conv)

    app.add_handler(CallbackQueryHandler(view_sales, pattern="^view_sales$"))

    # TODO: Implement edit/delete flows similarly!
