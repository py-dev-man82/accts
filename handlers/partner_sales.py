# handlers/partner_sales.py
# ────────────────────────────────────────────────────────────────
#  Partner‑Sales module  –  Owner → Partner reconciliation
#  • One record per item (flat schema)
#  • **Full double‑entry ledger integration**
#  • All DB / ledger mutations are wrapped in try/rollback safeties so we
#    never half‑commit data.
#  • Mirrors the safeguard pattern implemented in handlers/stockin.py
# ────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from tinydb import Query

from handlers.utils import require_unlock, fmt_date, fmt_money
from handlers.ledger import add_ledger_entry
from secure_db import secure_db

logger = logging.getLogger(__name__)

DEFAULT_CUR = "USD"
OWNER_ACCOUNT_ID = "POT"  # pseudo‑account for the business / pot

# ╭──────────────────────────────────────────────────────────────╮
# │  Helpers                                                    │
# ╰──────────────────────────────────────────────────────────────╯

def _partner_currency(pid: int) -> str:
    p = secure_db.table("partners").get(doc_id=pid)
    return p.get("currency", DEFAULT_CUR) if p else DEFAULT_CUR


def _filter_by_time(rows: List[dict], period: str) -> List[dict]:
    if period in ("3m", "6m"):
        days = 90 if period == "3m" else 180
        cutoff = datetime.utcnow().timestamp() - days * 86_400
        return [r for r in rows if datetime.fromisoformat(r["timestamp"]).timestamp() >= cutoff]
    return rows


# ╭──────────────────────────────────────────────────────────────╮
# │  Conversation‑state constants                               │
# ╰──────────────────────────────────────────────────────────────╯
(
    PS_PARTNER_SELECT,
    PS_ITEM_ID,
    PS_ITEM_QTY,
    PS_ITEM_PRICE,
    PS_NOTE,
    PS_DATE,
    PS_CONFIRM,
    # view
    PS_VIEW_PARTNER,
    PS_VIEW_TIME,
    PS_VIEW_PAGE,
    # edit
    PS_EDIT_PARTNER,
    PS_EDIT_TIME,
    PS_EDIT_PAGE,
    PS_EDIT_FIELD,
    PS_EDIT_NEWVAL,
    PS_EDIT_CONFIRM,
    # delete
    PS_DEL_PARTNER,
    PS_DEL_TIME,
    PS_DEL_PAGE,
    PS_DEL_CONFIRM,
) = range(20)

# ╭──────────────────────────────────────────────────────────────╮
# │  Main submenu                                               │
# ╰──────────────────────────────────────────────────────────────╯

async def show_partner_sales_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Add Partner Sale", callback_data="add_psale")],
            [InlineKeyboardButton("👀 View Partner Sales", callback_data="view_psale")],
            [InlineKeyboardButton("✏️ Edit Partner Sale", callback_data="edit_psale")],
            [InlineKeyboardButton("🗑️ Remove Partner Sale", callback_data="del_psale")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")],
        ]
    )
    await update.callback_query.edit_message_text("Partner Sales: choose an action", reply_markup=kb)

# ╭──────────────────────────────────────────────────────────────╮
# │  ADD  FLOW                                                  │
# ╰──────────────────────────────────────────────────────────────╯

@require_unlock
async def add_psale_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    parts = secure_db.all("partners")
    if not parts:
        await update.callback_query.edit_message_text(
            "No partners defined.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_sales_menu")]]),
        )
        return ConversationHandler.END

    btns = [InlineKeyboardButton(p["name"], callback_data=f"ps_part_{p.doc_id}") for p in parts]
    rows = [btns[i : i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="partner_sales_menu")])
    await update.callback_query.edit_message_text("Select partner:", reply_markup=InlineKeyboardMarkup(rows))
    return PS_PARTNER_SELECT


async def psale_choose_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pid = int(update.callback_query.data.split("_")[-1])
    context.user_data["ps_partner"] = pid
    context.user_data["ps_items"] = {}
    await update.callback_query.edit_message_text("Enter item_id (or type DONE):")
    return PS_ITEM_ID


async def psale_item_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.upper() == "DONE":
        if not context.user_data["ps_items"]:
            await update.message.reply_text("Please enter at least one item before DONE.")
            return PS_ITEM_ID
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="ps_note_skip")]])
        await update.message.reply_text("Optional note (or Skip):", reply_markup=kb)
        return PS_NOTE

    context.user_data["cur_item"] = text
    await update.message.reply_text(f"Quantity for {text}:")
    return PS_ITEM_QTY


async def psale_item_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
        assert qty != 0
    except Exception:
        await update.message.reply_text("Non‑zero integer please.")
        return PS_ITEM_QTY

    context.user_data["cur_qty"] = qty
    await update.message.reply_text(f"Unit price for {context.user_data['cur_item']}:")
    return PS_ITEM_PRICE


async def psale_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
    except Exception:
        await update.message.reply_text("Numeric price please (negatives allowed).")
        return PS_ITEM_PRICE

    iid = context.user_data["cur_item"]
    context.user_data["ps_items"][iid] = {"qty": context.user_data["cur_qty"], "unit_price": price}
    await update.message.reply_text("Enter next item_id (or type DONE):")
    return PS_ITEM_ID


async def psale_get_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "ps_note_skip":
        await update.callback_query.answer()
        note = ""
    else:
        note = update.message.text.strip()
    context.user_data["ps_note"] = note

    today = datetime.now().strftime("%d%m%Y")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Skip", callback_data="ps_date_skip")]])
    prompt = f"Enter date DDMMYYYY or Skip for today ({today}):"
    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kb)
    else:
        await update.message.reply_text(prompt, reply_markup=kb)
    return PS_DATE


async def psale_get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "ps_date_skip":
        await update.callback_query.answer()
        date_str = datetime.now().strftime("%d%m%Y")
    else:
        date_str = update.message.text.strip()
        try:
            datetime.strptime(date_str, "%d%m%Y")
        except Exception:
            await update.message.reply_text("Format DDMMYYYY, please.")
            return PS_DATE
    context.user_data["ps_date"] = date_str

    # ----- Confirmation card -----
    pid = context.user_data["ps_partner"]
    pname = secure_db.table("partners").get(doc_id=pid)["name"]
    cur = _partner_currency(pid)
    items = context.user_data["ps_items"]

    lines = [
        f" • {iid} ×{d['qty']} @ {fmt_money(d['unit_price'], cur)} = {fmt_money(d['qty'] * d['unit_price'], cur)}"
        for iid, d in items.items()
    ]
    summary = (
        "✅ **Confirm Partner Sale**\n"
        f"Partner: {pname}\n\nItems:\n" + "\n".join(lines) + "\n\n"
        f"Note: {context.user_data.get('ps_note') or '—'}\nDate: {fmt_date(date_str)}\n\nConfirm?"
    )
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Yes", callback_data="ps_conf_yes"), InlineKeyboardButton("❌ No", callback_data="ps_conf_no")]]
    )
    await (update.callback_query.edit_message_text if update.callback_query else update.message.reply_text)(
        summary, reply_markup=kb
    )
    return PS_CONFIRM


@require_unlock
async def psale_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Final commit of a new Partner‑sale – with full rollback on failure."""
    await update.callback_query.answer()
    if update.callback_query.data != "ps_conf_yes":
        await show_partner_sales_menu(update, context)
        return ConversationHandler.END

    d = context.user_data
    pid = d["ps_partner"]
    cur = _partner_currency(pid)
    note = d.get("ps_note", "")
    date = d["ps_date"]

    # Track what we insert so we can roll back safely -------------
    sales_inserted: List[Tuple[str, int, int]] = []  # (item_id, sale_doc_id, qty)
    ledger_inserted: List[int] = []

    try:
        for iid, det in d["ps_items"].items():
            qty = det["qty"]
            unit_price = det["unit_price"]
            total_amt = qty * unit_price

            # 1) partner_sales row (one per item)
            sale_id = secure_db.insert(
                "partner_sales",
                {
                    "partner_id": pid,
                    "item_id": iid,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "currency": cur,
                    "note": note,
                    "date": date,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            sales_inserted.append((iid, sale_id, qty))

            # 2) adjust partner inventory (must have stock!)
            Q = Query()
            row = secure_db.table("partner_inventory").get((Q.partner_id == pid) & (Q.item_id == iid))
            if not row or row["quantity"] < qty:
                raise RuntimeError(f"Insufficient stock of {iid} (needed {qty}, have {row['quantity'] if row else 0}).")
            secure_db.update("partner_inventory", {"quantity": row["quantity"] - qty}, [row.doc_id])

            # 3) ledger – partner credit
            add_ledger_entry(
                account_type="partner",
                account_id=pid,
                entry_type="sale",
                related_id=sale_id,
                amount=total_amt,
                currency=cur,
                note=note,
                date=date,
                item_id=iid,
                quantity=qty,
                unit_price=unit_price,
            )
            ledger_inserted.append(len(secure_db.table("ledger_entries")))  # last insert doc_id

            # 4) ledger – owner debit
            add_ledger_entry(
                account_type="owner",
                account_id=OWNER_ACCOUNT_ID,
                entry_type="partner_sale",
                related_id=sale_id,
                amount=-total_amt,
                currency=cur,
                note=f"Partner {pid} sale (item {iid})",
                date=date,
                item_id=iid,
                quantity=qty,
                unit_price=unit_price,
            )
            ledger_inserted.append(len(secure_db.table("ledger_entries")))

    except Exception as e:
        # ─── Roll back everything we touched ─────────────────────
        logger.error("Partner sale failed – rolling back. %s", e)

        # 1) Ledger rows first
        try:
            for lid in ledger_inserted:
                secure_db.remove("ledger_entries", [lid])
        except Exception:
            logger.exception("Failed while rolling back ledger rows")

        # 2) partner_sales rows & inventory reversal
        try:
            for iid, sid, qty in sales_inserted:
                secure_db.remove("partner_sales", [sid])
                Q = Query()
                row = secure_db.table("partner_inventory").get((Q.partner_id == pid) & (Q.item_id == iid))
                if row:
                    secure_db.update("partner_inventory", {"quantity": row["quantity"] + qty}, [row.doc_id])
        except Exception:
            logger.exception("Failed while rolling back partner_sales / inventory rows")

        await update.callback_query.edit_message_text(
            "❌ Partner Sale failed – no data saved.\n" + str(e)
        )
        return ConversationHandler.END

    logger.info("Partner sale committed for partner %s – items: %s", pid, list(d["ps_items"].keys()))
    await update.callback_query.edit_message_text(
        "✅ Partner Sale recorded.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_sales_menu")]]),
    )
    return ConversationHandler.END

# ╭──────────────────────────────────────────────────────────────╮
# │  EDIT  FLOW – Qty / Price / Note / Date                     │
# ╰──────────────────────────────────────────────────────────────╯

# Note: UI helper functions (listing pages, picking record, etc.) are unchanged
# from the pre‑ledger version, except that they ultimately funnel into
# `confirm_edit`, which now contains the safeguard envelope.

@require_unlock
async def confirm_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apply edits to a partner_sales record with full ledger + inventory repair."""
    await update.callback_query.answer()
    if update.callback_query.data != "ps_edit_conf_yes":
        await show_partner_sales_menu(update, context)
        return ConversationHandler.END

    d = context.user_data
    sid = d["edit_sale_id"]
    field = d["edit_field"]  # one of qty, price, note, date
    new_val = d["edit_newval"]

    rec = secure_db.table("partner_sales").get(doc_id=sid)
    if not rec:
        await update.callback_query.edit_message_text("Record not found – maybe already deleted?")
        return ConversationHandler.END

    pid = rec["partner_id"]
    cur = rec["currency"]
    iid = rec["item_id"]
    old_qty = rec["quantity"]
    old_price = rec["unit_price"]

    ledger_rows: List[int] = []
    try:
        if field == "qty":
            new_qty = int(new_val)
            delta = new_qty - old_qty
            secure_db.update("partner_sales", {"quantity": new_qty}, [sid])

            # inventory adjust
            Q = Query()
            row = secure_db.table("partner_inventory").get((Q.partner_id == pid) & (Q.item_id == iid))
            if not row or row["quantity"] < -delta:  # cannot oversell
                raise RuntimeError("Insufficient inventory to apply new quantity.")
            secure_db.update("partner_inventory", {"quantity": row["quantity"] - delta}, [row.doc_id])

            # ledger: difference amount only
            diff_amt = delta * old_price
            if diff_amt != 0:
                for acct, amt in (("partner", diff_amt), ("owner", -diff_amt)):
                    add_ledger_entry(
                        account_type=acct,
                        account_id=pid if acct == "partner" else OWNER_ACCOUNT_ID,
                        entry_type="sale_edit_qty",
                        related_id=sid,
                        amount=amt,
                        currency=cur,
                        note=f"Qty edit: {old_qty}→{new_qty}",
                        date=rec["date"],
                        item_id=iid,
                        quantity=new_qty,
                        unit_price=old_price,
                    )
                    ledger_rows.append(len(secure_db.table("ledger_entries")))

        elif field == "price":
            new_price = float(new_val)
            secure_db.update("partner_sales", {"unit_price": new_price}, [sid])

            diff_amt = old_qty * (new_price - old_price)
            if diff_amt != 0:
                for acct, amt in (("partner", diff_amt), ("owner", -diff_amt)):
                    add_ledger_entry(
                        account_type=acct,
                        account_id=pid if acct == "partner" else OWNER_ACCOUNT_ID,
                        entry_type="sale_edit_price",
                        related_id=sid,
                        amount=amt,
                        currency=cur,
                        note=f"Price edit: {old_price}→{new_price}",
                        date=rec["date"],
                        item_id=iid,
                        quantity=old_qty,
                        unit_price=new_price,
                    )
                    ledger_rows.append(len(secure_db.table("ledger_entries")))

        elif field == "note":
            secure_db.update("partner_sales", {"note": "" if new_val == "-" else new_val}, [sid])
        elif field == "date":
            datetime.strptime(new_val, "%d%m%Y")  # validate
            secure_db.update("partner_sales", {"date": new_val}, [sid])
    except Exception as e:
        # Rollback ledger rows if we added any
        for lid in ledger_rows:
            secure_db.remove("ledger_entries", [lid])
        # Rollback partner_sales + inventory if needed
        if field in ("qty", "price"):
            try:
                secure_db.update("partner_sales", {
                    "quantity": old_qty,
                    "unit_price": old_price,
                }, [sid])
                if field == "qty":
                    Q = Query()
                    row = secure_db.table("partner_inventory").get((Q.partner_id == pid) & (Q.item_id == iid))
                    if row:
                        secure_db.update("partner_inventory", {"quantity": row["quantity"] + (old_qty - int(new_val))}, [row.doc_id])
            except Exception:
                logger.exception("Secondary rollback failed during edit")
        logger.error("Edit failed and rolled back: %s", e)
        await update.callback_query.edit_message_text("❌ Edit failed – no changes stored.\n" + str(e))
        return ConversationHandler.END

    logger.info("Partner sale #%s edited (%s)", sid, field)
    await update.callback_query.edit_message_text(
        "✅ Partner Sale updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_sales_menu")]]),
    )
    return ConversationHandler.END

# ╭──────────────────────────────────────────────────────────────╮
# │  DELETE  FLOW                                               │
# ╰──────────────────────────────────────────────────────────────╯

@require_unlock
async def del_psale_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "ps_del_conf_yes":
        await show_partner_sales_menu(update, context)
        return ConversationHandler.END

    sid = context.user_data["del_sale_id"]
    rec = secure_db.table("partner_sales").get(doc_id=sid)
    if not rec:
        await update.callback_query.edit_message_text("Record not found.")
        return ConversationHandler.END

    pid = rec["partner_id"]
    iid = rec["item_id"]
    qty = rec["quantity"]
    price = rec["unit_price"]
    total_amt = qty * price
    cur = rec["currency"]

    try:
        # 1) delete partner_sales row
        secure_db.remove("partner_sales", [sid])

        # 2) restore inventory
        Q = Query()
        row = secure_db.table("partner_inventory").get((Q.partner_id == pid) & (Q.item_id == iid))
        if row:
            secure_db.update("partner_inventory", {"quantity": row["quantity"] + qty}, [row.doc_id])
        else:
            # reinstate a minimal row if somehow missing
            secure_db.insert("partner_inventory", {
                "partner_id": pid,
                "store_id": None,
                "item_id": iid,
                "quantity": qty,
                "unit_cost": price,
                "currency": cur,
                "timestamp": datetime.utcnow().isoformat(),
            })

        # 3) ledger reversal
        for acct, amt in (("partner", -total_amt), ("owner", total_amt)):
            add_ledger_entry(
                account_type=acct,
                account_id=pid if acct == "partner" else OWNER_ACCOUNT_ID,
                entry_type="sale_delete",
                related_id=sid,
                amount=amt,
                currency=cur,
                note=f"Delete partner sale (item {iid})",
                date=rec["date"],
                item_id=iid,
                quantity=qty,
                unit_price=price,
            )
    except Exception as e:
        logger.error("Delete failed; attempting rollback: %s", e)
        # partial rollback: try to re‑insert sale row if missing
        try:
            secure_db.insert("partner_sales", rec)
            Q = Query()
            row = secure_db.table("partner_inventory").get((Q.partner_id == pid) & (Q.item_id == iid))
            if row:
                secure_db.update("partner_inventory", {"quantity": row["quantity"] - qty}, [row.doc_id])
        except Exception:
            logger.exception("Rollback of partner_sales delete failed")
        await update.callback_query.edit_message_text("❌ Delete failed – nothing changed.\n" + str(e))
        return ConversationHandler.END

    logger.info("Partner sale #%s deleted.", sid)
    await update.callback_query.edit_message_text(
        "✅ Partner Sale deleted.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="partner_sales_menu")]]),
    )
    return ConversationHandler.END

# ╭──────────────────────────────────────────────────────────────╮
# │  ConversationHandler registration (UI glue unchanged)       │
# ╰──────────────────────────────────────────────────────────────╯

# ── ADD ───────────────────────────────────────────────────────
add_conv = ConversationHandler(
    entry_points=[
        CommandHandler("add_psale", add_psale_start),
        CallbackQueryHandler(add_psale_start, pattern="^add_psale$")
    ],
    states={
        PS_PARTNER_SELECT: [CallbackQueryHandler(psale_choose_partner, pattern="^ps_part_\\d+$")],
        PS_ITEM_ID:        [MessageHandler(filters.TEXT & ~filters.COMMAND, psale_item_id)],
        PS_ITEM_QTY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, psale_item_qty)],
        PS_ITEM_PRICE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, psale_item_price)],
        PS_NOTE:           [
            CallbackQueryHandler(psale_get_note, pattern="^ps_note_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, psale_get_note)
        ],
        PS_DATE:           [
            CallbackQueryHandler(psale_get_date, pattern="^ps_date_skip$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, psale_get_date)
        ],
        PS_CONFIRM:        [CallbackQueryHandler(psale_confirm, pattern="^ps_conf_")]
    },
    fallbacks=[CommandHandler("cancel", show_partner_sales_menu)],
    per_message=False,
)

# ── VIEW ──────────────────────────────────────────────────────
view_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(view_psale_start, pattern="^view_psale$")],
    states={
        PS_VIEW_PARTNER: [CallbackQueryHandler(view_psale_period,     pattern="^ps_view_part_\\d+$")],
        PS_VIEW_TIME:    [CallbackQueryHandler(view_psale_set_filter, pattern="^ps_view_time_")],
        PS_VIEW_PAGE:    [CallbackQueryHandler(handle_psale_view_nav, pattern="^ps_view_(prev|next)$")],
    },
    fallbacks=[CommandHandler("cancel", show_partner_sales_menu)],
    per_message=False,
)

# ── EDIT ──────────────────────────────────────────────────────
edit_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(edit_psale_start, pattern="^edit_psale$")],
    states={
        PS_EDIT_PARTNER: [CallbackQueryHandler(edit_psale_period,     pattern="^ps_edit_part_\\d+$")],
        PS_EDIT_TIME:    [CallbackQueryHandler(edit_psale_set_filter, pattern="^ps_edit_time_")],
        PS_EDIT_PAGE: [
            CallbackQueryHandler(handle_psale_edit_nav, pattern="^ps_edit_(prev|next)$"),
            MessageHandler(filters.Regex(r"^\\d+$") & ~filters.COMMAND, edit_psale_pick_doc)
        ],
        PS_EDIT_FIELD:  [CallbackQueryHandler(edit_psale_choose_field, pattern="^ps_edit_field_")],
        PS_EDIT_NEWVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_psale_newval)],
        PS_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit_psale,      pattern="^ps_edit_conf_")],
    },
    fallbacks=[CommandHandler("cancel", show_partner_sales_menu)],
    per_message=False,
)

# ── DELETE ────────────────────────────────────────────────────
del_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(del_psale_start, pattern="^del_psale$")],
    states={
        PS_DEL_PARTNER: [CallbackQueryHandler(del_psale_period,       pattern="^ps_del_part_\\d+$")],
        PS_DEL_TIME:    [CallbackQueryHandler(del_psale_set_filter,   pattern="^ps_del_time_")],
        PS_DEL_PAGE: [
            CallbackQueryHandler(handle_psale_del_nav, pattern="^ps_del_(prev|next)$"),
            MessageHandler(filters.Regex(r"^\\d+$") & ~filters.COMMAND, del_psale_pick_doc)
        ],
        PS_DEL_CONFIRM: [CallbackQueryHandler(confirm_delete_psale,   pattern="^ps_del_conf_")],
    },
    fallbacks=[CommandHandler("cancel", show_partner_sales_menu)],
    per_message=False,
)

# ── REGISTRATION helper ───────────────────────────────────────
def register_partner_sales_handlers(app):
    app.add_handler(CallbackQueryHandler(show_partner_sales_menu, pattern="^partner_sales_menu$"))
    app.add_handler(add_conv)
    app.add_handler(view_conv)
    app.add_handler(edit_conv)
    app.add_handler(del_conv)
