from telegram import Update from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes import pandas as pd from io import BytesIO from secure_db import secure_db

List of tables to export

TABLES = [ 'customers', 'stores', 'partners', 'customer_sales', 'customer_payments', 'partner_payouts', 'store_inventory', 'partner_inventory', 'handling_fees', 'store_handling_income', 'pot' ]

async def export_excel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE): # Allow both /export_excel and inline button try: secure_db.ensure_unlocked() except RuntimeError as e: return await update.message.reply_text(str(e))

# Load tables into DataFrames
writer_buf = BytesIO()
with pd.ExcelWriter(writer_buf, engine='xlsxwriter') as writer:
    for tbl in TABLES:
        df = pd.DataFrame(secure_db.all(tbl))
        # Capitalize sheet name
        sheet = tbl.capitalize()
        df.to_excel(writer, sheet_name=sheet, index=False)
writer_buf.seek(0)

# Send as document
if update.message:
    await update.message.reply_document(
        document=writer_buf,
        filename='accounting_export.xlsx',
        caption='📁 Exported full accounting workbook'
    )
else:
    await update.callback_query.answer()
    await update.callback_query.message.reply_document(
        document=writer_buf,
        filename='accounting_export.xlsx',
        caption='📁 Exported full accounting workbook'
    )

def register_export_handler(app): # Register as a command app.add_handler(CommandHandler('export_excel', export_excel_cmd)) # Register for inline button callback app.add_handler(CallbackQueryHandler(export_excel_cmd, pattern='^export_excel$'))

