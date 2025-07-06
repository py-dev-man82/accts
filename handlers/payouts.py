# handlers/payouts.py
import logging
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from handlers.utils import require_unlock
from secure_db import secure_db

# ── State constants ───────────────────────────────────────────────
(
    P_PARTNER_SELECT,
    P_LOCAL_AMT,
    P_FEE_PERC,
    P_USD_PAID,
    P_NOTE,
    P_CONFIRM,
    P_EDIT_PARTNER,
    P_EDIT_SELECT,
    P_EDIT_LOCAL,
    P_EDIT_FEE,
    P_EDIT_USD,
    P_EDIT_NOTE,
    P_EDIT_CONFIRM,
    P_DELETE_PARTNER,
    P_DELETE_SELECT,
    P_DELETE_CONFIRM,
) = range(16)

# ── Sub-menu ──────────────────────────────────────────────────────
async def show_payout_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Payout",    callback_data="add_payout")],
        [InlineKeyboardButton("👀 View Payouts", callback_data="view_payout")],
        [InlineKeyboardButton("✏️ Edit Payout",  callback_data="edit_payout")],
        [InlineKeyboardButton("🗑️ Remove Payout",callback_data="remove_payout")],
        [InlineKeyboardButton("🔙 Main Menu",    callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text("Payouts: choose an action", reply_markup=kb)

# =================================================================
#                             ADD FLOW
# =================================================================
@require_unlock
async def add_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners = secure_db.all('partners')
    if not partners:
        await update.callback_query.edit_message_text(
            "No partners available.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="payout_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(p['name'], callback_data=f"pout_{p.doc_id}") for p in partners]
    kb = InlineKeyboardMarkup([buttons[i:i+2] for i in range(0, len(buttons), 2)])
    await update.callback_query.edit_message_text("Select a partner:", reply_markup=kb)
    return P_PARTNER_SELECT

async def get_payout_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data['partner_id'] = int(update.callback_query.data.split('_')[-1])
    await update.callback_query.edit_message_text("Enter local amount to pay:")
    return P_LOCAL_AMT

async def get_payout_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt = float(update.message.text); assert amt>0
    except:
        await update.message.reply_text("Positive number please.")
        return P_LOCAL_AMT
    context.user_data['local_amt'] = amt
    await update.message.reply_text("Enter handling fee % (e.g. 2.5) or 0 if none:")
    return P_FEE_PERC

async def get_payout_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pct = float(update.message.text); assert 0<=pct<100
    except:
        await update.message.reply_text("0–99 please.")
        return P_FEE_PERC
    d=context.user_data; d['fee_perc']=pct; d['fee_amt']=d['local_amt']*pct/100
    await update.message.reply_text("Enter USD paid:")
    return P_USD_PAID

async def get_payout_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd=float(update.message.text)
    except:
        await update.message.reply_text("Number please.")
        return P_USD_PAID
    context.user_data['usd_amt']=usd
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note",callback_data="note_skip")]])
    await update.message.reply_text("Enter an optional note or press Skip:", reply_markup=kb)
    return P_NOTE

async def get_payout_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handles both text reply and skip button, like payments.py
    if update.callback_query:          # user pressed Skip
        await update.callback_query.answer()
        note=""
    else:                              # user typed a note
        note=update.message.text.strip()
    d=context.user_data; d['note']=note
    # ── Build confirmation summary
    net=d['local_amt']-d['fee_amt']; fx=net/d['usd_amt'] if d['usd_amt'] else 0
    summary=(f"Local: {d['local_amt']:.2f}\n"
             f"Fee: {d['fee_perc']:.2f}% ({d['fee_amt']:.2f})\n"
             f"USD Paid: {d['usd_amt']:.2f}\n"
             f"FX Rate: {fx:.4f}\n"
             f"Note: {note or '—'}")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes",callback_data="pout_conf_yes"),
                              InlineKeyboardButton("❌ No", callback_data="pout_conf_no")]])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary,reply_markup=kb)
    else:
        await update.message.reply_text(summary,reply_markup=kb)
    return P_CONFIRM

@require_unlock
async def confirm_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data!="pout_conf_yes":
        await show_payout_menu(update,context); return ConversationHandler.END
    d=context.user_data
    secure_db.insert('partner_payouts',{
        'partner_id':d['partner_id'],
        'local_amt': d['local_amt'],
        'fee_perc':  d['fee_perc'],
        'fee_amt':   d['fee_amt'],
        'usd_amt':   d['usd_amt'],
        'fx_rate':   (d['local_amt']-d['fee_amt'])/d['usd_amt'] if d['usd_amt'] else 0,
        'note':      d.get('note',''),
        'timestamp': datetime.utcnow().isoformat(),
    })
    await update.callback_query.edit_message_text(
        f"✅ Payout of {d['local_amt']:.2f} recorded.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payout_menu")]]))
    return ConversationHandler.END

# =================================================================
#                        VIEW  (unchanged)
# =================================================================
async def view_payouts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows=secure_db.all('partner_payouts')
    if not rows:
        text="No payouts found."
    else:
        lines=[]
        for r in rows:
            p=secure_db.table('partners').get(doc_id=r['partner_id'])
            name=p['name'] if p else "Unknown"
            lines.append(f"[{r.doc_id}] {name}: {r['local_amt']:.2f} "
                         f"(fee {r.get('fee_perc',0):.2f}%={r.get('fee_amt',0):.2f}) "
                         f"→ {r.get('usd_amt',0):.2f} USD | Note: {r.get('note','')}")
        text="Payouts:\n"+"\n".join(lines)
    await update.callback_query.edit_message_text(text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payout_menu")]]))

# =================================================================
#                        EDIT  FLOW
# =================================================================
@require_unlock
async def edit_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners=secure_db.all('partners')
    buttons=[InlineKeyboardButton(p['name'],callback_data=f"pout_edit_{p.doc_id}") for p in partners]
    kb=InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select partner:",reply_markup=kb)
    return P_EDIT_PARTNER

async def get_edit_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid=int(update.callback_query.data.rsplit('_',1)[1])
    rows=[r for r in secure_db.all('partner_payouts') if r['partner_id']==pid]
    if not rows:
        await show_payout_menu(update,context); return ConversationHandler.END
    buttons=[InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}->{r.get('usd_amt',0):.2f}",
                                  callback_data=f"pout_edit_sel_{r.doc_id}") for r in rows]
    kb=InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select payout to edit:",reply_markup=kb)
    return P_EDIT_SELECT

async def get_edit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did=int(update.callback_query.data.rsplit('_',1)[1])
    rec=secure_db.table('partner_payouts').get(doc_id=did)
    context.user_data.update({'edit_id':did,'local_amt':rec['local_amt'],
                              'fee_perc':rec.get('fee_perc',0),'fee_amt':rec.get('fee_amt',0),
                              'usd_amt':rec.get('usd_amt',0),'note':rec.get('note','')})
    await update.callback_query.edit_message_text("Enter new local amount:")
    return P_EDIT_LOCAL

async def get_edit_local(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amt=float(update.message.text); assert amt>0
    except:
        await update.message.reply_text("Positive number please."); return P_EDIT_LOCAL
    context.user_data['local_amt']=amt
    await update.message.reply_text("Enter new handling fee % (e.g. 2.5) or 0 if none:")
    return P_EDIT_FEE

async def get_edit_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pct=float(update.message.text); assert 0<=pct<100
    except:
        await update.message.reply_text("0–99 please."); return P_EDIT_FEE
    d=context.user_data; d['fee_perc']=pct; d['fee_amt']=d['local_amt']*pct/100
    await update.message.reply_text("Enter new USD paid:")
    return P_EDIT_USD

async def get_edit_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        usd=float(update.message.text)
    except:
        await update.message.reply_text("Number please."); return P_EDIT_USD
    context.user_data['usd_amt']=usd
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip note",callback_data="note_skip")]])
    await update.message.reply_text("Enter an optional note or press Skip:",reply_markup=kb)
    return P_EDIT_NOTE

async def get_edit_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer(); note=""
    else:
        note=update.message.text.strip()
    d=context.user_data; d['note']=note
    net=d['local_amt']-d['fee_amt']; fx=net/d['usd_amt'] if d['usd_amt'] else 0
    summary=(f"Local: {d['local_amt']:.2f}\n"
             f"Fee: {d['fee_perc']:.2f}% ({d['fee_amt']:.2f})\n"
             f"USD Paid: {d['usd_amt']:.2f}\n"
             f"FX Rate: {fx:.4f}\n"
             f"Note: {note or '—'}")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Save",callback_data="pout_save_yes"),
                              InlineKeyboardButton("❌ Cancel",callback_data="pout_save_no")]])
    if update.callback_query:
        await update.callback_query.edit_message_text(summary,reply_markup=kb)
    else:
        await update.message.reply_text(summary,reply_markup=kb)
    return P_EDIT_CONFIRM

@require_unlock
async def confirm_edit_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data!="pout_save_yes":
        await show_payout_menu(update,context); return ConversationHandler.END
    d=context.user_data; did=d['edit_id']
    secure_db.update('partner_payouts',{
        'local_amt':d['local_amt'],'fee_perc':d['fee_perc'],'fee_amt':d['fee_amt'],
        'usd_amt':d['usd_amt'],'fx_rate':(d['local_amt']-d['fee_amt'])/d['usd_amt'] if d['usd_amt'] else 0,
        'note':d.get('note',''),
    },[did])
    await update.callback_query.edit_message_text(
        f"✅ Payout {did} updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payout_menu")]]))
    return ConversationHandler.END

# =================================================================
#                        DELETE FLOW  (unchanged)
# =================================================================
@require_unlock
async def delete_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    partners=secure_db.all('partners')
    buttons=[InlineKeyboardButton(p['name'],callback_data=f"pout_del_{p.doc_id}") for p in partners]
    kb=InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select partner:",reply_markup=kb)
    return P_DELETE_PARTNER

async def get_delete_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid=int(update.callback_query.data.split('_')[-1])
    rows=[r for r in secure_db.all('partner_payouts') if r['partner_id']==pid]
    if not rows:
        await show_payout_menu(update,context); return ConversationHandler.END
    buttons=[InlineKeyboardButton(f"[{r.doc_id}] {r['local_amt']:.2f}->{r.get('usd_amt',0):.2f}",
                                  callback_data=f"pout_del_sel_{r.doc_id}") for r in rows]
    kb=InlineKeyboardMarkup([buttons[i:i+2] for i in range(0,len(buttons),2)])
    await update.callback_query.edit_message_text("Select payout to delete:",reply_markup=kb)
    return P_DELETE_SELECT

async def confirm_delete_payout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    did=int(update.callback_query.data.split('_')[-1])
    secure_db.remove('partner_payouts',[did])
    await update.callback_query.edit_message_text(
        f"✅ Payout {did} deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="payout_menu")]]))
    return ConversationHandler.END

# ── Handler registration helper ───────────────────────────────────
def register_payout_handlers(app):
    app.add_handler(CallbackQueryHandler(show_payout_menu,pattern="^payout_menu$"))

    # Add
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add_payout",add_payout),
                      CallbackQueryHandler(add_payout,pattern="^add_payout$")],
        states={
            P_PARTNER_SELECT:[CallbackQueryHandler(get_payout_partner,pattern="^pout_\\d+$")],
            P_LOCAL_AMT:     [MessageHandler(filters.TEXT & ~filters.COMMAND,get_payout_local)],
            P_FEE_PERC:      [MessageHandler(filters.TEXT & ~filters.COMMAND,get_payout_fee)],
            P_USD_PAID:      [MessageHandler(filters.TEXT & ~filters.COMMAND,get_payout_usd)],
            P_NOTE:          [CallbackQueryHandler(get_payout_note,pattern="^note_skip$"),
                              MessageHandler(filters.TEXT & ~filters.COMMAND,get_payout_note)],
            P_CONFIRM:       [CallbackQueryHandler(confirm_payout,pattern="^pout_conf_")]
        },
        fallbacks=[CommandHandler("cancel",lambda u,c: show_payout_menu(u,c))],
        per_message=False))

    # View
    app.add_handler(CallbackQueryHandler(view_payouts,pattern="^view_payout$"))

    # Edit
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("edit_payout",edit_payout),
                      CallbackQueryHandler(edit_payout,pattern="^edit_payout$")],
        states={
            P_EDIT_PARTNER:[CallbackQueryHandler(get_edit_partner,pattern="^pout_edit_\\d+$")],
            P_EDIT_SELECT: [CallbackQueryHandler(get_edit_selection,pattern="^pout_edit_sel_\\d+$")],
            P_EDIT_LOCAL:  [MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_local)],
            P_EDIT_FEE:    [MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_fee)],
            P_EDIT_USD:    [MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_usd)],
            P_EDIT_NOTE:   [CallbackQueryHandler(get_edit_note,pattern="^note_skip$"),
                            MessageHandler(filters.TEXT & ~filters.COMMAND,get_edit_note)],
            P_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_payout,pattern="^pout_save_")],
        },
        fallbacks=[CommandHandler("cancel",lambda u,c: show_payout_menu(u,c))],
        per_message=False))

    # Delete
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("remove_payout",delete_payout),
                      CallbackQueryHandler(delete_payout,pattern="^remove_payout$")],
        states={
            P_DELETE_PARTNER:[CallbackQueryHandler(get_delete_partner,pattern="^pout_del_\\d+$")],
            P_DELETE_SELECT: [CallbackQueryHandler(confirm_delete_payout,pattern="^pout_del_sel_\\d+$")],
        },
        fallbacks=[CommandHandler("cancel",lambda u,c: show_payout_menu(u,c))],
        per_message=False))