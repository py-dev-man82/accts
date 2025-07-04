# handlers/export_excel.py

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
import pandas as pd
from io import BytesIO
from secure_db import secure_db

def register_export_handler(app):
    app.add_handler(CommandHandler('export_excel', export_excel))

async def export_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Gather tables
    tables = {
        name: pd.DataFrame(secure_db.all(name))
        for name in [
            'customers','stores','partners','items',
            'customer_sales','customer_payments',
            'partner_payouts','store_inventory',
            'partner_inventory','handling_fees'
        ]
    }
    # Write to Excel in memory
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine='xlsxwriter') as writer:
        for sheet, df in tables.items():
            df.to_excel(writer, sheet_name=sheet, index=False)
    bio.seek(0)
    await update.message.reply_document(document=bio, filename='export.xlsx')
