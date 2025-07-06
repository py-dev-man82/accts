# handlers/customers.py

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
    E_SELECT,    # edit select customer
    E_NAME,      # edit new name
    E_CUR,       # edit new currency
    E_CONFIRM,   # edit confirm
    R_SELECT,    # remove select customer
    R_CONFIRM    # remove confirm
) = range(9)

async def show_customer_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Display the customer management submenu.
    """
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Customer",    callback_data="add_customer")],
        [InlineKeyboardButton("👀 View Customers", callback_data="view_customer")],
        [InlineKeyboardButton("✏️ Edit Customer",  callback_data="edit_customer")],
        [InlineKeyboardButton("🗑️ Remove Customer", callback_data="remove_customer")],
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]
    ])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Customer Management: choose an action", reply_markup=kb
        )
    else:
        await update.message.reply_text(
            "Customer Management: choose an action", reply_markup=kb
        )
    return ConversationHandler.END

# --- Add Customer Flow ---
@require_unlock
async def add_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Enter new customer name:")
    else:
        await update.message.reply_text("Enter new customer name:")
    return C_NAME

async def get_customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['customer_name'] = name
    await update.message.reply_text(
        f"Name: {name}\nEnter currency code (e.g. USD, EUR):"
    )
    return C_CUR

async def get_customer_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    context.user_data['customer_currency'] = currency
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="cust_yes"),
         InlineKeyboardButton("❌ No",  callback_data="cust_no")]
    ])
    await update.message.reply_text(
        f"Name: {context.user_data['customer_name']}\n"
        f"Currency: {currency}\nSave?", reply_markup=kb
    )
    return C_CONFIRM

@require_unlock
async def confirm_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == 'cust_yes':
        secure_db.insert('customers', {
            'name': context.user_data['customer_name'],
            'currency': context.user_data['customer_currency'],
            'created_at': datetime.utcnow().isoformat()
        })
        await update.callback_query.edit_message_text(
            f"✅ Customer '{context.user_data['customer_name']}' added."
        )
    else:
        await update.callback_query.edit_message_text("❌ Add cancelled.")
    # Return to submenu
    return await show_customer_menu(update, context)

# --- View Customers Flow ---
@require_unlock
async def view_customers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = secure_db.all('customers')
    if not records:
        text = "No customers found."
    else:
        lines = [f"• [{r.doc_id}] {r['name']} ({r['currency']})" for r in records]
        text = "Customers:\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="customer_menu")]])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)
    return ConversationHandler.END

# --- Edit Customer Flow ---
async def edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # list customers to choose
    records = secure_db.all('customers')
    if not records:
        await update.message.reply_text("No customers to edit.")
        return await show_customer_menu(update, context)
    buttons = [[InlineKeyboardButton(f"{r['name']}", callback_data=f"edit_{r.doc_id}")] for r in records]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="customer_menu")])
    kb = InlineKeyboardMarkup(buttons)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Select customer to edit:", reply_markup=kb)
    else:
        await update.message.reply_text("Select customer to edit:", reply_markup=kb)
    return E_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[1])
    context.user_data['edit_cid'] = cid
    cust = Query()
    rec = secure_db.search('customers', cust.doc_id == cid)[0]
    await update.callback_query.edit_message_text(f"Editing {rec['name']} ({rec['currency']}). Enter new name:")
    return E_NAME

async def set_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data['edit_name'] = name
    await update.message.reply_text(f"New name: {name}\nEnter new currency code:")
    return E_CUR

async def set_edit_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    context.user_data['edit_currency'] = currency
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Save", callback_data="edit_yes"), InlineKeyboardButton("❌ Cancel", callback_data="edit_no")]])
    await update.message.reply_text(
        f"Update to: {context.user_data['edit_name']} ({currency})?", reply_markup=kb
    )
    return E_CONFIRM

@require_unlock
async def confirm_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = context.user_data['edit_cid']
    if update.callback_query.data == 'edit_yes':
        secure_db.update('customers', {
            'name': context.user_data['edit_name'],
            'currency': context.user_data['edit_currency']
        }, [cid])
        await update.callback_query.edit_message_text("✅ Customer updated.")
    else:
        await update.callback_query.edit_message_text("❌ Edit cancelled.")
    return await show_customer_menu(update, context)

# --- Remove Customer Flow ---
async def remove_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = secure_db.all('customers')
    if not records:
        await update.message.reply_text("No customers to remove.")
        return await show_customer_menu(update, context)
    buttons = [[InlineKeyboardButton(f"{r['name']}", callback_data=f"remove_{r.doc_id}")] for r in records]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="customer_menu")])
    kb = InlineKeyboardMarkup(buttons)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Select customer to remove:", reply_markup=kb)
    else:
        await update.message.reply_text("Select customer to remove:", reply_markup=kb)
    return R_SELECT

async def get_remove_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[1])
    context.user_data['remove_cid'] = cid
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data="remove_yes"), InlineKeyboardButton("❌ No", callback_data="remove_no")]])
    await update.callback_query.edit_message_text(
        f"Confirm removal of customer ID {cid}?", reply_markup=kb
    )
    return R_CONFIRM

@require_unlock
async def confirm_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = context.user_data['remove_cid']
    if update.callback_query.data == 'remove_yes':
        secure_db.remove('customers', [cid])
        await update.callback_query.edit_message_text("✅ Customer removed.")
    else:
        await update.callback_query.edit_message_text("❌ Removal cancelled.")
    return await show_customer_menu(update, context)

# --- Registration ---
def register_customer_handlers(app):
    # Show submenu
    app.add_handler(CallbackQueryHandler(show_customer_menu, pattern="^customer_menu$"))
    # Add, View, Edit, Remove flows
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_customer",     add_customer),
            CommandHandler("view_customer",    view_customers),
            CommandHandler("edit_customer",    edit_customer),
            CommandHandler("remove_customer",  remove_customer),
            CallbackQueryHandler(add_customer,    pattern="^add_customer$"),
            CallbackQueryHandler(view_customers, pattern="^view_customer$"),
            CallbackQueryHandler(edit_customer,  pattern="^edit_customer$"),
            CallbackQueryHandler(remove_customer,pattern="^remove_customer$"),
        ],
        states={
            C_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_name)],
            C_CUR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_customer_currency)],
            C_CONFIRM: [CallbackQueryHandler(confirm_customer, pattern="^cust_")],
            E_SELECT:  [CallbackQueryHandler(get_edit_selection, pattern="^edit_\d+")],
            E_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, set_edit_name)],
            E_CUR:     [MessageHandler(filters.TEXT & ~filters.COMMAND, set_edit_currency)],
            E_CONFIRM: [CallbackQueryHandler(confirm_edit, pattern="^edit_")],
            R_SELECT:  [CallbackQueryHandler(get_remove_selection, pattern="^remove_\d+")],
            R_CONFIRM: [CallbackQueryHandler(confirm_remove, pattern="^remove_")]
        },
        fallbacks=[CallbackQueryHandler(show_customer_menu, pattern="^main_menu$")],
        per_message=False
    )
    app.add_handler(conv)
