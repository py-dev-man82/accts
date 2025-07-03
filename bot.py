#!/usr/bin/env python3 import logging from datetime import datetime from io import BytesIO

import pandas as pd from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup from telegram.ext import ( ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, ContextTypes )

from secure_db import SecureDB import config

--- Logging ---

logging.basicConfig(level=logging.INFO) logger = logging.getLogger(name)

--- Initialize encrypted TinyDB ---

secure_db = SecureDB(config.DB_PATH, config.DB_PASSPHRASE)

--- Conversation states ---

( MAIN_MENU,

# Customer CRUD
C_NAME, C_CUR, C_CONFIRM,
C_SEL_EDIT, C_NEW_NAME, C_NEW_CUR, C_CONFIRM_EDIT,
C_SEL_REMOVE, C_CONFIRM_REMOVE,
C_SEL_VIEW,

# Store CRUD
S_NAME, S_CUR, S_CONFIRM,
S_SEL_EDIT, S_NEW_NAME, S_NEW_CUR, S_CONFIRM_EDIT,
S_SEL_REMOVE, S_CONFIRM_REMOVE,
S_SEL_VIEW,

# Partner CRUD
P_NAME, P_CUR, P_CONFIRM,
P_SEL_EDIT, P_NEW_NAME, P_NEW_CUR, P_CONFIRM_EDIT,
P_SEL_REMOVE, P_CONFIRM_REMOVE,
P_SEL_VIEW,

# Sales
SALE_CUST, SALE_STORE, SALE_ITEM,
SALE_QTY, SALE_PRICE, SALE_NOTE, SALE_CONFIRM,

# Payments
PAY_CUST, PAY_LOCAL, PAY_FEE, PAY_USD, PAY_CONFIRM,

# Payouts
PO_PART, PO_USD, PO_CONFIRM,

# Stock-In
SI_PART, SI_ITEM, SI_QTY, SI_COST, SI_CONFIRM,

# (Reports & Export use direct commands)

) = range(50)

--- Admin check decorator ---

def admin_only(func): async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE): if update.effective_user.id != config.ADMIN_TELEGRAM_ID: await update.message.reply_text("🚫 Unauthorized") return ConversationHandler.END return await func(update, ctx) return wrapper

--- Keyboards ---

def main_menu_kb(): return InlineKeyboardMarkup([ [InlineKeyboardButton("👥 Customers", callback_data='manage_customers')], [InlineKeyboardButton("🏬 Stores",    callback_data='manage_stores')], [InlineKeyboardButton("🤝 Partners",  callback_data='manage_partners')], [InlineKeyboardButton("🛒 Sales",     callback_data='manage_sales')], [InlineKeyboardButton("💰 Payments",  callback_data='manage_payments')], [InlineKeyboardButton("📦 Stock-In",  callback_data='manage_stockin')], [InlineKeyboardButton("📊 Reports",   callback_data='manage_reports')], [InlineKeyboardButton("📁 Export",    callback_data='export_excel')], [InlineKeyboardButton("🔒 Lock",      callback_data='lock')], ])

def entity_kb(title): t = title.lower() return InlineKeyboardMarkup([ [InlineKeyboardButton(f"➕ Add {title}",     callback_data=f'add_{t}')], [InlineKeyboardButton(f"✏️ Edit {title}",   callback_data=f'edit_{t}')], [InlineKeyboardButton(f"🗑️ Remove {title}", callback_data=f'remove_{t}')], [InlineKeyboardButton(f"👁️ View {title}",  callback_data=f'view_{t}')], [InlineKeyboardButton("◀️ Back",            callback_data='back_main')], ])

--- /start and menu routing ---

@admin_only async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int: await update.message.reply_text("Main Menu:", reply_markup=main_menu_kb()) return MAIN_MENU

async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int: query = update.callback_query; await query.answer() d = query.data

# Submenus
if d == 'manage_customers':
    return await query.edit_message_text("Manage Customers:", reply_markup=entity_kb("Customer"))
if d == 'manage_stores':
    return await query.edit_message_text("Manage Stores:", reply_markup=entity_kb("Store"))
if d == 'manage_partners':
    return await query.edit_message_text("Manage Partners:", reply_markup=entity_kb("Partner"))
if d == 'manage_sales':
    return await query.edit_message_text("Sales:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Sale", callback_data='add_sale')],
        [InlineKeyboardButton("◀️ Back",    callback_data='back_main')]
    ]))
if d == 'manage_payments':
    return await query.edit_message_text("Payments:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Payment", callback_data='add_payment')],
        [InlineKeyboardButton("◀️ Back",       callback_data='back_main')]
    ]))
if d == 'manage_stockin':
    return await query.edit_message_text("Stock-In:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Stock-In", callback_data='add_stockin')],
        [InlineKeyboardButton("◀️ Back",          callback_data='back_main')]
    ]))
if d == 'manage_reports':
    return await query.edit_message_text("Reports:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Customer Report", callback_data='rep_customer')],
        [InlineKeyboardButton("🤝 Partner Report",  callback_data='rep_partner')],
        [InlineKeyboardButton("🏬 Store Report",    callback_data='rep_store')],
        [InlineKeyboardButton("🛡️ Owner (POT)",     callback_data='rep_owner')],
        [InlineKeyboardButton("◀️ Back",             callback_data='back_main')]
    ]))
if d == 'back_main':
    return await start(update, ctx)
if d == 'lock':
    secure_db.lock()
    await query.edit_message_text("🔒 Locked.")
    return ConversationHandler.END

# Dispatch map
dispatch = {
    # Customers
    'add_customer':    ask_cust_name,
    'edit_customer':   select_cust_edit,
    'remove_customer': select_cust_remove,
    'view_customer':   select_cust_view,
    # Stores
    'add_store':       ask_store_name,
    'edit_store':      select_store_edit,
    'remove_store':    select_store_remove,
    'view_store':      select_store_view,
    # Partners
    'add_partner':     ask_part_name,
    'edit_partner':    select_part_edit,
    'remove_partner':  select_part_remove,
    'view_partner':    select_part_view,
    # Sales
    'add_sale':        select_sale_customer,
    # Payments
    'add_payment':     select_payment_customer,
    # Payouts
    'add_payout':      select_payout_partner,
    # Stock-In
    'add_stockin':     select_stockin_partner,
    # Export
    'export_excel':    export_excel_cmd,
    # Unlock
    'unlock':          unlock_cmd,
    # Reports
    'rep_customer':    weekly_report_customer,
    'rep_partner':     weekly_report_partner,
    'rep_store':       weekly_report_store,
    'rep_owner':       weekly_report_owner,
}
if d in dispatch:
    return await dispatch[d](update, ctx)

await query.edit_message_text("❓ Unknown option")
return MAIN_MENU

--- Unlock command ---

async def unlock_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE): secure_db.unlock() await update.message.reply_text("🔓 Unlocked.")

--- Export to Excel ---

async def export_excel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE): secure_db.ensure_unlocked() tables = [ 'customers','stores','partners', 'customer_sales','customer_payments','partner_payouts', 'store_inventory','partner_inventory', 'handling_fees','store_handling_income','pot' ] bio = BytesIO() with pd.ExcelWriter(bio, engine='xlsxwriter') as writer: for t in tables: df = pd.DataFrame(secure_db.all(t)) df.to_excel(writer, sheet_name=t.capitalize(), index=False) bio.seek(0) await update.message.reply_document( document=bio, filename='accounting_export.xlsx', caption='📁 Exported data' )

--- Cancel handler ---

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int: await update.message.reply_text("❌ Cancelled.") return MAIN_MENU

--- Main ---

def main(): app = ApplicationBuilder().token(config.BOT_TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler('start', start), CommandHandler('unlock', unlock_cmd)],
    states={
        MAIN_MENU: [CallbackQueryHandler(menu_handler)],
        # Map your state constants to handlers below
        # ... handlers definitions inserted earlier ...
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    allow_reentry=True
)

app.add_handler(conv)
app.run_polling()

if name == 'main': main()

