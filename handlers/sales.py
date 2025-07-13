# handlers/sales.py
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (f
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from tinydb import Query

from handlers.utils import require_unlock, fmt_money, fmt_date
from secure_db import secure_db
from handlers.ledger import add_ledger_entry, delete_ledger_entries_by_related

# ───────────────────────────────────────────────────────────────
#  Logger
# ───────────────────────────────────────────────────────────────
logger = logging.getLogger("sales")

# ───────────────────────────────────────────────────────────────
#  Quick helper – numeric ID from plain text
# ───────────────────────────────────────────────────────────────
def _extract_doc_id(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None

# ───────────────────────────────────────────────────────────────
#  Conversation-state constants
# ───────────────────────────────────────────────────────────────
(
    S_CUST_SELECT,  S_STORE_SELECT, S_ITEM_QTY,  S_PRICE,
    S_FEE,          S_NOTE,         S_CONFIRM,

    S_EDIT_SELECT,  S_EDIT_TIME,    S_EDIT_PAGE,
    S_EDIT_FIELD,   S_EDIT_NEWVAL,  S_EDIT_CONFIRM,

    S_DELETE_SELECT,S_DELETE_CONFIRM,

    S_VIEW_CUSTOMER,S_VIEW_TIME,    S_VIEW_PAGE,
) = range(18)

# ───────────────────────────────────────────────────────────────
#  SALES MENU
# ───────────────────────────────────────────────────────────────
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
    msg = "Sales: choose an action"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

# ======================================================================
#                                ADD FLOW
# ======================================================================
@require_unlock
async def add_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers configured.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]]
            ),
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"sale_cust_{c.doc_id}")
               for c in customers]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text("Select customer:",
                                                  reply_markup=InlineKeyboardMarkup(rows))
    return S_CUST_SELECT

async def get_sale_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data["sale_customer"] = cid

    stores = secure_db.all("stores")
    if not stores:
        await update.callback_query.edit_message_text(
            "No stores configured.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]]
            ),
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{s['name']} ({s['currency']})",
                                    callback_data=f"sale_store_{s.doc_id}")
               for s in stores]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text("Select store:",
                                                  reply_markup=InlineKeyboardMarkup(rows))
    return S_STORE_SELECT

async def get_sale_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split("_")[-1])
    context.user_data["sale_store"] = sid

    # show inventory
    q = Query()
    inv_rows = secure_db.table("store_inventory").search(q.store_id == sid)
    inv_txt = ("\n".join([f"• Item {r['item_id']}: {r['quantity']}"
                          for r in inv_rows]) or "No inventory.")
    await update.callback_query.edit_message_text(
        f"📦 Inventory:\n{inv_txt}\n\nEnter item_id,quantity (e.g. 7,3):"
    )
    return S_ITEM_QTY

async def get_sale_item_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "," not in text:
        await update.message.reply_text("❌ Format: item_id,quantity  (e.g. 7,3)")
        return S_ITEM_QTY

    item_part, qty_part = text.split(",", 1)
    item_id = item_part.strip()          # ← always string!
    try:
        qty = int(qty_part.strip())
        assert qty > 0
    except Exception:
        await update.message.reply_text("❌ Quantity must be a positive integer.")
        return S_ITEM_QTY

    # stock check
    sid = context.user_data["sale_store"]
    q   = Query()
    rec = secure_db.table("store_inventory").get(
        (q.store_id == sid) & (q.item_id == item_id)
    )
    if not rec or rec["quantity"] < qty:
        avail = rec["quantity"] if rec else 0
        await update.message.reply_text(
            f"❌ Not enough stock (available {avail}). Try again:"
        )
        return S_ITEM_QTY

    context.user_data.update({"sale_item": item_id, "sale_qty": qty})
    await update.message.reply_text("Unit price:")
    return S_PRICE

async def get_sale_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text)
        assert price >= 0
    except Exception:
        await update.message.reply_text("Enter a numeric price:")
        return S_PRICE

    context.user_data["sale_price"] = price
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="fee_skip")]])
    await update.message.reply_text("Handling fee (or Skip):", reply_markup=kb)
    return S_FEE

async def get_sale_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "fee_skip":
        await update.callback_query.answer()
        fee = 0.0
    else:
        try:
            fee = float(update.message.text)
            assert fee >= 0
        except Exception:
            await update.message.reply_text("Numeric fee or press Skip:")
            return S_FEE
    context.user_data["sale_fee"] = fee
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="note_skip")]])
    await update.message.reply_text("Optional note (or Skip):", reply_markup=kb)
    return S_NOTE

async def get_sale_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Determine note from callback or message
    if update.callback_query and update.callback_query.data == "note_skip":
        await update.callback_query.answer()
        note = ""
    else:
        note = update.message.text.strip()
    context.user_data["sale_note"] = note

    d = context.user_data
    cust  = secure_db.table("customers").get(doc_id=d["sale_customer"])
    store = secure_db.table("stores").get(doc_id=d["sale_store"])
    cur   = store["currency"]
    total = d["sale_qty"] * d["sale_price"]
    total_fee = d["sale_fee"] * d["sale_qty"]

    summary = (
        f"✅ **Confirm Sale**\n"
        f"Customer: {cust['name']}\n"
        f"Store: {store['name']} ({cur})\n"
        f"Item {d['sale_item']} ×{d['sale_qty']}\n"
        f"Unit:  {fmt_money(d['sale_price'], cur)}\n"
        f"Total: {fmt_money(total, cur)}\n"
        f"Fee:   {fmt_money(total_fee, cur)}\n"
        f"Note:  {note or '—'}\n\nConfirm?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="sale_yes"),
         InlineKeyboardButton("❌ No",  callback_data="sale_no")]
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=kb)
    else:
        await update.message.reply_text(summary, reply_markup=kb)

    return S_CONFIRM

# ───────────────────────────────────────────────────────────────
#  Confirm-Sale handler  (add + ledger + inventory)
# ───────────────────────────────────────────────────────────────
@require_unlock
async def confirm_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "sale_yes":
        await show_sales_menu(update, context)
        return ConversationHandler.END

    d            = context.user_data
    store_row    = secure_db.table("stores").get(doc_id=d["sale_store"])
    cur          = store_row["currency"]
    total_fee    = d["sale_fee"] * d["sale_qty"]
    total_sale   = d["sale_qty"] * d["sale_price"]
    sale_date    = datetime.utcnow().strftime("%d%m%Y")
    sale_ts      = datetime.utcnow().isoformat()
    item_id      = d["sale_item"]
    qty          = d["sale_qty"]
    unit_price   = d["sale_price"]
    note         = d["sale_note"]

    # ── identify buyer type (customer / partner) ─────────────────
    buyer        = secure_db.table("customers").get(doc_id=d["sale_customer"])
    buyer_type   = buyer.get("type", "customer") if buyer else "customer"
    store_id     = d["sale_store"]
    customer_id  = d["sale_customer"]

    sale_id          = None
    ledger_written   = []

    try:
        # 1️⃣  sales row ----------------------------------------------------
        sale_id = secure_db.insert("sales", {
            "customer_id":  customer_id,
            "store_id":     store_id,
            "item_id":      item_id,
            "quantity":     qty,
            "unit_price":   unit_price,
            "handling_fee": total_fee,
            "note":         note,
            "currency":     cur,
            "timestamp":    sale_ts,
        })

        # 2️⃣  inventory decrement ----------------------------------------
        q        = Query()
        inv_rec  = secure_db.table("store_inventory").get(
            (q.store_id == store_id) & (q.item_id == item_id)
        )
        if inv_rec is None or inv_rec["quantity"] < qty:
            raise Exception(f"Not enough stock for item '{item_id}'.")
        new_qty = inv_rec["quantity"] - qty

        logger.debug(
            "[confirm_sale] inventory-update store:%s item:%s  %s → %s",
            store_id, item_id, inv_rec["quantity"], new_qty
        )
        secure_db.update(
            "store_inventory",
            {"quantity": new_qty},
            [inv_rec.doc_id]                # ← list of doc-ids  ✅
        )

        # 3️⃣  handling-fee tracking (store_payments) ----------------------
        if total_fee > 0:
            secure_db.insert("store_payments", {
                "store_id":  store_id,
                "amount":    total_fee,
                "currency":  cur,
                "note":      "Handling fee for sale",
                "timestamp": sale_ts,
            })

        # 4️⃣  LEDGER WRITES ───────────────────────────────────────────────
        logger.debug(
            "[confirm_sale] → buyer ledger  %s:%s  sale_id=%s",
            buyer_type, customer_id, sale_id
        )
        add_ledger_entry(
            account_type = buyer_type,
            account_id   = customer_id,
            entry_type   = "sale",
            related_id   = sale_id,
            amount       = -total_sale,
            currency     = cur,
            note         = note,
            date         = sale_date,
            timestamp    = sale_ts,
            item_id      = item_id,
            quantity     = -qty,            # inventory out
            unit_price   = unit_price,
            store_id     = store_id,
        )
        ledger_written.append((buyer_type, customer_id, sale_id))

        logger.debug(
            "[confirm_sale] → store ledger (inventory) store:%s  sale_id=%s",
            store_id, sale_id
        )
        add_ledger_entry(
            account_type = "store",
            account_id   = store_id,
            entry_type   = "sale",
            related_id   = sale_id,
            amount       = 0,               # revenue accounted elsewhere
            currency     = cur,
            note         = "",
            date         = sale_date,
            timestamp    = sale_ts,
            item_id      = item_id,
            quantity     = -qty,
            unit_price   = unit_price,
            store_id     = store_id,
        )
        ledger_written.append(("store", store_id, sale_id))

        # 4c. handling-fee ledger (only when a fee exists) -----------------
        if total_fee > 0:
            if buyer_type == "customer":
                logger.debug(
                    "[confirm_sale] → handling-fee ledger store:%s sale_id=%s",
                    store_id, sale_id
                )
                add_ledger_entry(
                    account_type = "store",
                    account_id   = store_id,
                    entry_type   = "handling_fee",
                    related_id   = sale_id,
                    amount       = total_fee,
                    currency     = cur,
                    note         = "",
                    date         = sale_date,
                    timestamp    = sale_ts,
                    item_id      = item_id,
                    quantity     = qty,
                    unit_price   = d["sale_fee"],
                    store_id     = store_id,
                )
                ledger_written.append(("store", store_id, sale_id))
            else:  # partner buyer
                logger.debug(
                    "[confirm_sale] → handling-fee ledger partner:%s & store:%s sale_id=%s",
                    customer_id, store_id, sale_id
                )
                # partner (debit)
                add_ledger_entry(
                    account_type = "partner",
                    account_id   = customer_id,
                    entry_type   = "handling_fee",
                    related_id   = sale_id,
                    amount       = -total_fee,
                    currency     = cur,
                    note         = "",
                    date         = sale_date,
                    timestamp    = sale_ts,
                    item_id      = item_id,
                    quantity     = qty,
                    unit_price   = d["sale_fee"],
                    store_id     = store_id,
                )
                ledger_written.append(("partner", customer_id, sale_id))
                # store (credit)
                add_ledger_entry(
                    account_type = "store",
                    account_id   = store_id,
                    entry_type   = "handling_fee",
                    related_id   = sale_id,
                    amount       = total_fee,
                    currency     = cur,
                    note         = "",
                    date         = sale_date,
                    timestamp    = sale_ts,
                    item_id      = item_id,
                    quantity     = qty,
                    unit_price   = d["sale_fee"],
                    store_id     = store_id,
                )
                ledger_written.append(("store", store_id, sale_id))

    except Exception as e:
        logger.exception("[confirm_sale] exception – rolling back")
        # rollback sales row
        if sale_id is not None:
            try:
                secure_db.remove("sales", [sale_id])
            except Exception:
                pass
        # rollback ledger rows
        for acct_type, acct_id, rel_id in ledger_written:
            try:
                delete_ledger_entries_by_related(acct_type, acct_id, rel_id)
            except Exception:
                pass
        # rollback inventory
        try:
            q = Query()
            rec = secure_db.table("store_inventory").get(
                (q.store_id == store_id) & (q.item_id == item_id)
            )
            if rec:
                secure_db.update(
                    "store_inventory",
                    {"quantity": rec["quantity"] + qty},
                    [rec.doc_id]
                )
        except Exception:
            pass
        await update.callback_query.edit_message_text(
            f"❌ Sale aborted, error: {e}"
        )
        return ConversationHandler.END

    # success message
    await update.callback_query.edit_message_text(
        "✅ Sale recorded, inventory and ledger updated.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]]
        ),
    )
    return ConversationHandler.END


# ======================================================================
#                                EDIT FLOW
# ======================================================================
@require_unlock
async def edit_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    custs = secure_db.all("customers")
    if not custs:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="sales_menu")]]))
        return ConversationHandler.END
    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"edit_cust_{c.doc_id}")
               for c in custs]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text("Select customer:",
                                                  reply_markup=InlineKeyboardMarkup(rows))
    return S_EDIT_SELECT

async def get_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "edit_time_back":
        return await edit_sale(update, context)
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data.update({"edit_customer_id": cid, "edit_page": 1})
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 M", callback_data="edit_time_3m"),
         InlineKeyboardButton("📅 Last 6 M", callback_data="edit_time_6m")],
        [InlineKeyboardButton("🗓️ All",      callback_data="edit_time_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="edit_sale")],
    ])
    await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
    return S_EDIT_TIME

async def get_edit_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_time_filter"] = update.callback_query.data.split("_")[-1]
    context.user_data["edit_page"] = 1
    return await send_edit_page(update, context)

async def send_edit_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = context.user_data["edit_customer_id"]
    filt = context.user_data["edit_time_filter"]
    page = context.user_data["edit_page"]
    size = 20

    rows = [r for r in secure_db.all("sales") if r["customer_id"] == cid]
    if filt in ("3m", "6m"):
        cut = datetime.utcnow().timestamp() - (90 if filt=="3m" else 180)*86400
        rows = [r for r in rows if datetime.fromisoformat(r["timestamp"]).timestamp() >= cut]

    total_pages = max(1, (len(rows)+size-1)//size)
    chunk = rows[(page-1)*size: page*size]
    if not chunk:
        await update.callback_query.edit_message_text(
            "No sales in that window.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="edit_sale")]]))
        return ConversationHandler.END

    lines = []
    for r in chunk:
        unit = fmt_money(r["unit_price"], r["currency"])
        tot  = fmt_money(r["unit_price"]*r["quantity"], r["currency"])
        lines.append(f"{r.doc_id}: Item {r['item_id']} ×{r['quantity']} @ {unit} = {tot}")
    text = (f"✏️ **Edit Sales**  P{page}/{total_pages}\n\n" +
            "\n".join(lines) +
            "\n\nReply with record ID or use arrows.")

    nav = []
    if page > 1: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="edit_prev"))
    if page < total_pages: nav.append(InlineKeyboardButton("➡️ Next", callback_data="edit_next"))
    nav.append(InlineKeyboardButton("🔙 Back", callback_data="edit_time_back"))
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([nav]))
    return S_EDIT_PAGE

async def handle_edit_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "edit_prev":
        context.user_data["edit_page"] -= 1
    elif update.callback_query.data == "edit_next":
        context.user_data["edit_page"] += 1
    elif update.callback_query.data == "edit_time_back":
        return await get_edit_customer(update, context)
    return await send_edit_page(update, context)

async def select_edit_sale_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = _extract_doc_id(update.message.text)
    if sid is None:
        await update.message.reply_text("Numeric ID please.")
        return S_EDIT_PAGE
    rec = secure_db.table("sales").get(doc_id=sid)
    if not rec or rec["customer_id"] != context.user_data["edit_customer_id"]:
        await update.message.reply_text("That ID isn’t in the current list.")
        return S_EDIT_PAGE

    context.user_data["edit_sale_id"] = sid
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Store",           callback_data="edit_field_store")],
        [InlineKeyboardButton("Item & Quantity", callback_data="edit_field_itemqty")],
        [InlineKeyboardButton("Unit Price",      callback_data="edit_field_price")],
        [InlineKeyboardButton("Handling Fee",    callback_data="edit_field_fee")],
        [InlineKeyboardButton("Note",            callback_data="edit_field_note")],
        [InlineKeyboardButton("🔙 Cancel",       callback_data="edit_time_back")],
    ])
    await update.message.reply_text(f"Editing sale #{sid}. Choose field:", reply_markup=kb)
    return S_EDIT_FIELD

async def get_edit_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split("_")[-1])
    context.user_data["edit_sale_id"] = sid
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Store",           callback_data="edit_field_store")],
        [InlineKeyboardButton("Item & Quantity", callback_data="edit_field_itemqty")],
        [InlineKeyboardButton("Unit Price",      callback_data="edit_field_price")],
        [InlineKeyboardButton("Handling Fee",    callback_data="edit_field_fee")],
        [InlineKeyboardButton("Note",            callback_data="edit_field_note")],
        [InlineKeyboardButton("🔙 Cancel",       callback_data="edit_time_back")],
    ])
    await update.callback_query.edit_message_text("Choose field:", reply_markup=kb)
    return S_EDIT_FIELD

async def get_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    field = update.callback_query.data.split("_")[-1]
    context.user_data["edit_field"] = field

    if field == "store":
        stores = secure_db.all("stores")
        buttons = [InlineKeyboardButton(f"{s['name']} ({s['currency']})",
                                        callback_data=f"edit_new_store_{s.doc_id}")
                   for s in stores]
        rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        rows.append([InlineKeyboardButton("🔙 Cancel", callback_data="edit_time_back")])
        await update.callback_query.edit_message_text("Select new store:",
                                                      reply_markup=InlineKeyboardMarkup(rows))
    elif field == "itemqty":
        await update.callback_query.edit_message_text("New item_id,quantity (e.g. 5,25):")
    elif field == "price":
        await update.callback_query.edit_message_text("New unit price:")
    elif field == "fee":
        await update.callback_query.edit_message_text("New handling fee (0 for none):")
    elif field == "note":
        await update.callback_query.edit_message_text("New note (or '-' to clear):")
    return S_EDIT_NEWVAL

async def save_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_value"] = update.message.text.strip()
    field = context.user_data["edit_field"]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="edit_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="edit_conf_no")]
    ])
    await update.message.reply_text(
        f"Change **{field}** to `{context.user_data['new_value']}` ?",
        reply_markup=kb
    )
    return S_EDIT_CONFIRM

@require_unlock
async def confirm_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "edit_conf_yes":
        await show_sales_menu(update, context)
        return ConversationHandler.END

    sid   = context.user_data["edit_sale_id"]
    field = context.user_data["edit_field"]
    new   = context.user_data["new_value"]

    # Fetch sale before editing to get old values for ledger removal
    sale = secure_db.table("sales").get(doc_id=sid)

    # --- UPDATE DB RECORD ---
    if field == "store":
        secure_db.update("sales", {"store_id": int(new)}, [sid])
    elif field == "itemqty":
        item_part, qty_part = new.split(",", 1)
        item_id = item_part.strip()
        qty     = int(qty_part.strip())
        secure_db.update("sales", {"item_id": item_id, "quantity": qty}, [sid])
    elif field == "price":
        secure_db.update("sales", {"unit_price": float(new)}, [sid])
    elif field == "fee":
        secure_db.update("sales", {"handling_fee": float(new)}, [sid])
    elif field == "note":
        secure_db.update("sales", {"note": "" if new == "-" else new}, [sid])

    # --- LEDGER PATCH: Remove old entries ---
    try:
        delete_ledger_entries_by_related("customer", sale["customer_id"], sid)
        if sale["handling_fee"] > 0:
            delete_ledger_entries_by_related("store", sale["store_id"], sid)
    except Exception as e:
        logging.error(f"[sales-edit] Failed to delete previous ledger entries for sale {sid}: {e}")

    # --- LEDGER PATCH: Add new entries for updated sale ---
    # Fetch updated sale
    updated_sale = secure_db.table("sales").get(doc_id=sid)
    if updated_sale:
        try:
            # Customer ledger
            add_ledger_entry(
                account_type="customer",
                account_id=updated_sale["customer_id"],
                entry_type="sale",
                related_id=sid,
                amount=-(updated_sale["quantity"] * updated_sale["unit_price"] + updated_sale.get("handling_fee", 0)),
                currency=updated_sale["currency"],
                note=f"Sale {updated_sale['item_id']} ×{updated_sale['quantity']}" + (f" + handling fee {updated_sale.get('handling_fee', 0)}" if updated_sale.get("handling_fee", 0) else ""),
                date=datetime.utcnow().strftime("%d%m%Y"),
                timestamp=updated_sale["timestamp"],
            )
            # Store ledger (only if handling fee present and > 0)
            if updated_sale.get("handling_fee", 0) > 0:
                add_ledger_entry(
                    account_type="store",
                    account_id=updated_sale["store_id"],
                    entry_type="handling_fee",
                    related_id=sid,
                    amount=updated_sale["handling_fee"],
                    currency=updated_sale["currency"],
                    note="Handling fee for customer sale (edited)",
                    date=datetime.utcnow().strftime("%d%m%Y"),
                    timestamp=updated_sale["timestamp"],
                )
        except Exception as e:
            logging.error(f"[sales-edit] Failed to add new ledger entries for sale {sid}: {e}")

    await update.callback_query.edit_message_text(
        "✅ Sale updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                 callback_data="sales_menu")]]))
    return ConversationHandler.END

# ======================================================================
#                                DELETE FLOW
# ======================================================================
@require_unlock
async def delete_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    custs = secure_db.all("customers")
    if not custs:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="sales_menu")]]))
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"del_cust_{c.doc_id}")
               for c in custs]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text("Select customer:",
                                                  reply_markup=InlineKeyboardMarkup(rows))
    return S_DELETE_SELECT

async def get_delete_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data["delete_customer_id"] = cid

    rows = [r for r in secure_db.all("sales") if r["customer_id"] == cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No sales.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="sales_menu")]]))
        return ConversationHandler.END

    lines = [f"{r.doc_id}: Item {r['item_id']} ×{r['quantity']} "
             f"= {fmt_money(r['quantity']*r['unit_price'], r['currency'])}"
             for r in rows]
    await update.callback_query.edit_message_text(
        "Reply with record ID to delete:\n\n" + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                 callback_data="sales_menu")]]))
    return S_DELETE_CONFIRM

async def select_delete_sale_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = _extract_doc_id(update.message.text)
    if sid is None:
        await update.message.reply_text("Numeric ID please.")
        return S_DELETE_CONFIRM
    sale = secure_db.table("sales").get(doc_id=sid)
    if not sale or sale["customer_id"] != context.user_data["delete_customer_id"]:
        await update.message.reply_text("ID not in list.")
        return S_DELETE_CONFIRM

    context.user_data.update({"del_sale": sale, "del_id": sid})
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="del_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="del_conf_no")]
    ])
    await update.message.reply_text(f"Delete sale #{sid}?", reply_markup=kb)
    return S_DELETE_CONFIRM

@require_unlock
async def perform_delete_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "del_conf_yes":
        await show_sales_menu(update, context)
        return ConversationHandler.END

    sale = context.user_data["del_sale"]
    sid  = context.user_data["del_id"]

    # restore inventory
    q = Query()
    rec = secure_db.table("store_inventory").get(
        (q.store_id == sale["store_id"]) & (q.item_id == sale["item_id"])
    )
    if rec:
        secure_db.update("store_inventory",
                         {"quantity": rec["quantity"] + sale["quantity"]},
                         [rec.doc_id])

    # reverse handling fee if any
    if sale.get("handling_fee", 0) > 0:
        secure_db.insert("store_payments", {
            "store_id": sale["store_id"],
            "amount":  -sale["handling_fee"],
            "currency": sale["currency"],
            "note":     f"Reversal of fee for deleted sale #{sid}",
            "timestamp":datetime.utcnow().isoformat(),
        })

    # --- LEDGER PATCH: Remove ledger entries ---
    try:
        delete_ledger_entries_by_related("customer", sale["customer_id"], sid)
        if sale.get("handling_fee", 0) > 0:
            delete_ledger_entries_by_related("store", sale["store_id"], sid)
    except Exception as e:
        logging.error(f"[sales-delete] Failed to delete ledger entries for sale {sid}: {e}")

    # remove sale record
    secure_db.remove("sales", [sid])
    await update.callback_query.edit_message_text(
        f"✅ Sale #{sid} deleted.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                 callback_data="sales_menu")]]))
    return ConversationHandler.END

# ======================================================================
#                                VIEW FLOW
# ======================================================================
@require_unlock
async def view_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    custs = secure_db.all("customers")
    if not custs:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="sales_menu")]]))
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"view_cust_{c.doc_id}")
               for c in custs]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text("Select customer:",
                                                  reply_markup=InlineKeyboardMarkup(rows))
    return S_VIEW_CUSTOMER

async def get_view_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "view_time_back":
        return await view_sales(update, context)
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data.update({"view_customer_id": cid, "view_page": 1})

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 M", callback_data="view_time_3m"),
         InlineKeyboardButton("📅 Last 6 M", callback_data="view_time_6m")],
        [InlineKeyboardButton("🗓️ All",      callback_data="view_time_all")],
        [InlineKeyboardButton("🔙 Back",     callback_data="view_sales")],
    ])
    await update.callback_query.edit_message_text("Select period:", reply_markup=kb)
    return S_VIEW_TIME

async def get_view_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_time_filter"] = update.callback_query.data.split("_")[-1]
    context.user_data["view_page"] = 1
    return await send_sales_page(update, context)

async def send_sales_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid  = context.user_data["view_customer_id"]
    filt = context.user_data["view_time_filter"]
    page = context.user_data["view_page"]
    size = 20

    rows = [r for r in secure_db.all("sales") if r["customer_id"] == cid]
    if filt in ("3m", "6m"):
        cut = datetime.utcnow().timestamp() - (90 if filt=="3m" else 180)*86400
        rows = [r for r in rows if datetime.fromisoformat(r["timestamp"]).timestamp() >= cut]

    total_pages = max(1, (len(rows)+size-1)//size)
    chunk = rows[(page-1)*size: page*size]

    if not chunk:
        await update.callback_query.edit_message_text(
            "No sales.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                                     callback_data="view_sales")]]))
        return ConversationHandler.END

    lines = [f"{r.doc_id}: Item {r['item_id']} ×{r['quantity']} "
             f"@ {fmt_money(r['unit_price'], r['currency'])} "
             f"= {fmt_money(r['unit_price']*r['quantity'], r['currency'])}"
             for r in chunk]
    text = f"📄 **Sales**  P{page}/{total_pages}\n\n" + "\n".join(lines)

    nav = []
    if page > 1: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="view_prev"))
    if page < total_pages: nav.append(InlineKeyboardButton("➡️ Next", callback_data="view_next"))
    nav.append(InlineKeyboardButton("🔙 Back", callback_data="view_time_back"))
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([nav]))
    return S_VIEW_PAGE

async def handle_view_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data == "view_prev":
        context.user_data["view_page"] -= 1
    elif update.callback_query.data == "view_next":
        context.user_data["view_page"] += 1
    elif update.callback_query.data == "view_time_back":
        return await get_view_customer(update, context)
    return await send_sales_page(update, context)

# ======================================================================
#                        CONVERSATION HANDLERS
# ======================================================================
add_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(add_sale, pattern="^add_sale$"),
                  CommandHandler("add_sale", add_sale)],
    states={
        S_CUST_SELECT:  [CallbackQueryHandler(get_sale_customer, pattern="^sale_cust_")],
        S_STORE_SELECT: [CallbackQueryHandler(get_sale_store,  pattern="^sale_store_")],
        S_ITEM_QTY:     [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_item_qty)],
        S_PRICE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_price)],
        S_FEE:          [CallbackQueryHandler(get_sale_fee, pattern="^fee_skip$"),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_fee)],
        S_NOTE:         [CallbackQueryHandler(get_sale_note, pattern="^note_skip$"),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, get_sale_note)],
        S_CONFIRM:      [CallbackQueryHandler(confirm_sale, pattern="^sale_")],
    },
    fallbacks=[CommandHandler("cancel", show_sales_menu)],
    per_message=False,
)

edit_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(edit_sale, pattern="^edit_sale$")],
    states={
        S_EDIT_SELECT: [CallbackQueryHandler(get_edit_customer, pattern="^edit_cust_"),
                        CallbackQueryHandler(edit_sale,        pattern="^edit_sale$")],
        S_EDIT_TIME:   [CallbackQueryHandler(get_edit_time,     pattern="^edit_time_"),
                        CallbackQueryHandler(edit_sale,        pattern="^edit_sale$")],
        S_EDIT_PAGE:   [CallbackQueryHandler(handle_edit_pagination, pattern="^edit_(prev|next)$"),
                        CallbackQueryHandler(get_edit_customer,      pattern="^edit_time_back$"),
                        CallbackQueryHandler(get_edit_sale,          pattern="^edit_sale_\\d+$"),
                        MessageHandler(filters.Regex(r"^\d+$") & ~filters.COMMAND,
                                       select_edit_sale_by_id)],
        S_EDIT_FIELD:  [CallbackQueryHandler(get_edit_field, pattern="^edit_field_")],
        S_EDIT_NEWVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit)],
        S_EDIT_CONFIRM:[CallbackQueryHandler(confirm_edit, pattern="^edit_conf_")],
    },
    fallbacks=[CommandHandler("cancel", show_sales_menu)],
    per_message=False,
)

delete_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(delete_sale, pattern="^remove_sale$")],
    states={
        S_DELETE_SELECT:  [CallbackQueryHandler(get_delete_customer, pattern="^del_cust_")],
        S_DELETE_CONFIRM: [CallbackQueryHandler(perform_delete_sale, pattern="^del_conf_"),
                           MessageHandler(filters.Regex(r"^\d+$") & ~filters.COMMAND,
                                          select_delete_sale_by_id)],
    },
    fallbacks=[CommandHandler("cancel", show_sales_menu)],
    per_message=False,
)

view_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(view_sales, pattern="^view_sales$")],
    states={
        S_VIEW_CUSTOMER: [CallbackQueryHandler(get_view_customer, pattern="^view_cust_"),
                          CallbackQueryHandler(view_sales,       pattern="^view_sales$")],
        S_VIEW_TIME:     [CallbackQueryHandler(get_view_time,     pattern="^view_time_"),
                          CallbackQueryHandler(view_sales,       pattern="^view_sales$")],
        S_VIEW_PAGE:     [CallbackQueryHandler(handle_view_pagination, pattern="^view_(prev|next)$"),
                          CallbackQueryHandler(get_view_customer,      pattern="^view_time_back$")],
    },
    fallbacks=[CommandHandler("cancel", show_sales_menu)],
    per_message=False,
)

# ======================================================================
#                     REGISTER HANDLERS TO APP
# ======================================================================
def register_sales_handlers(app):
    app.add_handler(CallbackQueryHandler(show_sales_menu, pattern="^sales_menu$"))
    app.add_handler(add_conv)
    app.add_handler(edit_conv)
    app.add_handler(delete_conv)
    app.add_handler(view_conv)
