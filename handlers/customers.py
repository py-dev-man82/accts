# handlers/customers.py

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

# State constants for the customer flow
(
    C_NAME,
    C_CUR,
    C_CONFIRM,
    C_EDIT_SELECT,
    C_EDIT_NAME,
    C_EDIT_CUR,
    C_EDIT_CONFIRM,
    C_DELETE_SELECT,
    C_DELETE_CONFIRM,
) = range(9)


# --- Submenu for Customer Management ---
async def show_customer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Showing customer submenu")
    if update.callback_query:
        await update.callback_query.answer()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Customer",     callback_data="add_customer")],
            [InlineKeyboardButton("👀 View Customers",  callback_data="view_customer")],
            [InlineKeyboardButton("✏️ Edit Customer",   callback_data="edit_customer")],
            [InlineKeyboardButton("🗑️ Remove Customer", callback_data="remove_customer")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ])
        await update.callback_query.edit_message_text(
            "Customer Management: choose an action",
            reply_markup=kb
        )


# --- Add Customer Flow ---
@require_unlock
async def add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start add_customer")
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Enter new customer name:")
    else:
        await update.message.reply_text("Enter new customer name:")
    return C_NAME


async def get_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received customer name: %s", update.message.text)
    context.user_data['customer_name'] = update.message.text.strip()
    await update.message.reply_text("Enter currency code for this customer (e.g. USD):")
    return C_CUR


async def get_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received currency: %s", update.message.text)
    context.user_data['customer_currency'] = update.message.text.strip().upper()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="cust_yes"),
         InlineKeyboardButton("❌ No",  callback_data="cust_no")],
    ])
    await update.message.reply_text(
        f"Name: {context.user_data['customer_name']}\n"
        f"Currency: {context.user_data['customer_currency']}\nSave?",
        reply_markup=kb
    )
    return C_CONFIRM


@require_unlock
async def confirm_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Confirm add_customer: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'cust_yes':
        secure_db.insert('customers', {
            'name':       context.user_data['customer_name'],
            'currency':   context.user_data['customer_currency'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            f"✅ Customer '{context.user_data['customer_name']}' added.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="customer_menu")
            ]])
        )
    else:
        await show_customer_menu(update, context)
    return ConversationHandler.END


# --- View Customers Flow ---
async def view_customers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("View customers")
    await update.callback_query.answer()
    rows = secure_db.all('customers')
    if not rows:
        text = "No customers found."
    else:
        lines = [f"• [{r.doc_id}] {r['name']} ({r['currency']})" for r in rows]
        text = "Customers:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back", callback_data="customer_menu")
    ]])
    await update.callback_query.edit_message_text(text, reply_markup=kb)


# --- Edit Customer Flow ---
@require_unlock
async def edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start edit_customer")
    await update.callback_query.answer()
    rows = secure_db.all('customers')
    if not rows:
        await update.callback_query.edit_message_text(
            "No customers to edit.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="customer_menu")
            ]])
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"edit_customer_{r.doc_id}")
        for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a customer to edit:", reply_markup=kb)
    return C_EDIT_SELECT


async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_edit_selection: %s", update.callback_query.data)
    await update.callback_query.answer()
    parts = update.callback_query.data.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await show_customer_menu(update, context)
    cid = int(parts[1])
    rec = secure_db.table('customers').get(doc_id=cid)
    if not rec:
        return await show_customer_menu(update, context)
    context.user_data['edit_cust'] = rec
    await update.callback_query.edit_message_text("Enter the new customer name:")
    return C_EDIT_NAME


async def get_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_edit_name: %s", update.message.text)
    context.user_data['new_name'] = update.message.text.strip()
    await update.message.reply_text("Enter the new currency code:")
    return C_EDIT_CUR


async def get_edit_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_edit_currency: %s", update.message.text)
    context.user_data['new_cur'] = update.message.text.strip().upper()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Save", callback_data="cust_conf_yes"),
        InlineKeyboardButton("❌ Cancel", callback_data="cust_conf_no")
    ]])
    await update.message.reply_text(
        f"Save changes for '{context.user_data['edit_cust']['name']}'?",
        reply_markup=kb
    )
    return C_EDIT_CONFIRM


@require_unlock
async def confirm_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_edit_customer: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'cust_conf_yes':
        rec = context.user_data['edit_cust']
        secure_db.update('customers', {
            'name': context.user_data['new_name'],
            'currency': context.user_data['new_cur']
        }, [rec.doc_id])
        await update.callback_query.edit_message_text(
            f"✅ Updated to {context.user_data['new_name']} "
            f"({context.user_data['new_cur']}).",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="customer_menu")
            ]])
        )
    else:
        await show_customer_menu(update, context)
    return ConversationHandler.END


# --- Delete Customer Flow ---
@require_unlock
async def delete_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Start delete_customer")
    await update.callback_query.answer()
    rows = secure_db.all('customers')
    if not rows:
        await update.callback_query.edit_message_text(
            "No customers to remove.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="customer_menu")
            ]])
        )
        return ConversationHandler.END

    buttons = [
        InlineKeyboardButton(f"{r['name']} ({r['currency']})", callback_data=f"delete_customer_{r.doc_id}")  
        for r in rows
    ]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a customer to delete:", reply_markup=kb)
    return C_DELETE_SELECT


async def get_delete_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("get_delete_selection: %s", update.callback_query.data)
    await update.callback_query.answer()
    parts = update.callback_query.data.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return await show_customer_menu(update, context)
    cid = int(parts[1])
    rec = secure_db.table('customers').get(doc_id=cid)
    if not rec:
        return await show_customer_menu(update, context)
    context.user_data['del_cust'] = rec
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, delete", callback_data="cust_del_yes"),
        InlineKeyboardButton("❌ No, cancel",  callback_data="cust_del_no")
    ]])
    await update.callback_query.edit_message_text(
        f"Are you sure you want to delete {rec['name']}?",
        reply_markup=kb
    )
    return C_DELETE_CONFIRM


@require_unlock
async def confirm_delete_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("confirm_delete_customer: %s", update.callback_query.data)
    await update.callback_query.answer()
    if update.callback_query.data == 'cust_del_yes':
        rec = context.user_data['del_cust']
        secure_db.remove('customers', [rec.doc_id])
        await update.callback_query.edit_message_text(
            f"✅ Customer '{rec['name']}' deleted.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="customer_menu")
            ]])
        )
    else:
        await show_customer_menu(update, context)
    return ConversationHandler.END


# --- Register Handlers ---
def register_customer_handlers(app):
    app.add_handler(CallbackQueryHandler(show_customer_menu, pattern="^customer_menu$"))

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_customer", add_customer),
            CallbackQueryHandler(add_customer, pattern="^add_customer$")
        ],
        states={
            C_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_name)],
            C_CUR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_currency)],
            C_CONFIRM: [CallbackQueryHandler(confirm_customer, pattern="^cust_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_customer)],
        per_message=False
    )
    app.add_handler(add_conv)

    app.add_handler(CallbackQueryHandler(view_customers, pattern="^view_customer$"))

    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit_customer", edit_customer),
            CallbackQueryHandler(edit_customer, pattern="^edit_customer$")
        ],
        states={
            C_EDIT_SELECT: [CallbackQueryHandler(get_edit_selection, pattern="^edit_customer_")],
            C_EDIT_NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_name)],
            C_EDIT_CUR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_currency)],
            C_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_customer, pattern="^cust_conf_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_edit_customer)],
        per_message=False
    )
    app.add_handler(edit_conv)

    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("remove_customer", delete_customer),
            CallbackQueryHandler(delete_customer, pattern="^remove_customer$")
        ],
        states={
            C_DELETE_SELECT: [CallbackQueryHandler(get_delete_selection, pattern="^delete_customer_")],
            C_DELETE_CONFIRM:[CallbackQueryHandler(confirm_delete_customer, pattern="^cust_del_")]
        },
        fallbacks=[CommandHandler("cancel", confirm_delete_customer)],
        per_message=False
    )
    app.add_handler(del_conv)