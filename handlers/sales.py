# handlers/sales.py
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from tinydb import Query

from handlers.utils import require_unlock
from secure_db import secure_db


# ────────────────────────────────────────────────────────────────
#  Utility – validate a numeric doc_id from user text
# ────────────────────────────────────────────────────────────────
def _extract_doc_id(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────
#  Conversation-state constants
# ────────────────────────────────────────────────────────────────
(
    S_CUST_SELECT,      # Add flow: customer select
    S_STORE_SELECT,     # Add flow: store select
    S_ITEM_QTY,         # Add flow: item/qty input
    S_PRICE,            # Add flow: price input
    S_FEE,              # Add flow: handling fee input
    S_NOTE,             # Add flow: note input
    S_CONFIRM,          # Add flow: confirm

    S_EDIT_SELECT,      # Edit flow: customer select
    S_EDIT_TIME,        # Edit flow: time filter
    S_EDIT_PAGE,        # Edit flow: paginated list
    S_EDIT_FIELD,       # Edit flow: choose field
    S_EDIT_NEWVAL,      # Edit flow: enter new value
    S_EDIT_CONFIRM,     # Edit flow: confirm change

    S_DELETE_SELECT,    # Delete flow: customer select
    S_DELETE_CONFIRM,   # Delete flow: confirm delete

    S_VIEW_CUSTOMER,    # View flow: customer select
    S_VIEW_TIME,        # View flow: time filter
    S_VIEW_PAGE,        # View flow: paginated list
) = range(18)


# ────────────────────────────────────────────────────────────────
#  SALES MENU
# ────────────────────────────────────────────────────────────────
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


# ────────────────────────────────────────────────────────────────
#  ADD FLOW
# ────────────────────────────────────────────────────────────────
@require_unlock
async def add_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    customers = secure_db.all("customers")
    if not customers:
        await update.callback_query.edit_message_text(
            "No customers found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{c['name']} ({c['currency']})",
                                    callback_data=f"sale_cust_{c.doc_id}") for c in customers]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text("Select customer:", reply_markup=InlineKeyboardMarkup(rows))
    return S_CUST_SELECT


async def get_sale_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data["sale_customer"] = cid

    stores = secure_db.all("stores")
    if not stores:
        await update.callback_query.edit_message_text(
            "No stores found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{s['name']} ({s['currency']})",
                                    callback_data=f"sale_store_{s.doc_id}") for s in stores]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text("Select store:", reply_markup=InlineKeyboardMarkup(rows))
    return S_STORE_SELECT


async def get_sale_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split("_")[-1])
    context.user_data["sale_store"] = sid

    # Show store inventory
    Inventory = Query()
    inv_rows = secure_db.table("store_inventory").search(Inventory.store_id == sid)
    if inv_rows:
        lines = [f"• Item {r['item_id']}: {r['quantity']} units" for r in inv_rows]
        inv_txt = "\n".join(lines)
    else:
        inv_txt = "No inventory found for this store."

    await update.callback_query.edit_message_text(
        f"📦 Current Inventory:\n{inv_txt}\n\nEnter item_id,quantity (e.g. 7,3):"
    )
    return S_ITEM_QTY


async def get_sale_item_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        item_id, qty = map(int, text.split(","))
    except Exception:
        await update.message.reply_text("❌ Format: item_id,quantity  (e.g. 7,3)")
        return S_ITEM_QTY

    # stock check
    sid = context.user_data["sale_store"]
    q = Query()
    rec = secure_db.table("store_inventory").get((q.store_id == sid) & (q.item_id == item_id))
    if not rec or rec["quantity"] < qty:
        avail = rec["quantity"] if rec else 0
        await update.message.reply_text(
            f"❌ Not enough stock. Available: {avail}. Enter a new item_id,quantity:"
        )
        return S_ITEM_QTY

    context.user_data.update({"sale_item": item_id, "sale_qty": qty})
    await update.message.reply_text("Enter unit price:")
    return S_PRICE


async def get_sale_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip())
    except Exception:
        await update.message.reply_text("Enter a numeric price:")
        return S_PRICE

    context.user_data["sale_price"] = price
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="fee_skip")]])
    await update.message.reply_text("Handling fee amount (or Skip):", reply_markup=kb)
    return S_FEE


async def get_sale_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "fee_skip":
        await update.callback_query.answer()
        fee = 0.0
    else:
        try:
            fee = float(update.message.text.strip())
        except Exception:
            await update.message.reply_text("Enter a numeric fee or press Skip:")
            return S_FEE

    context.user_data["sale_fee"] = fee
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➖ Skip", callback_data="note_skip")]])
    await update.message.reply_text("Optional note (or Skip):", reply_markup=kb)
    return S_NOTE


async def get_sale_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "note_skip":
        await update.callback_query.answer()
        note = ""
    else:
        note = update.message.text.strip()

    d = context.user_data
    cust = secure_db.table("customers").get(doc_id=d["sale_customer"])
    store = secure_db.table("stores").get(doc_id=d["sale_store"])
    total = d["sale_qty"] * d["sale_price"]

    summary = (
        f"✅ **Confirm Sale**\n"
        f"Customer: {cust['name']}\n"
        f"Store: {store['name']}\n"
        f"Item {d['sale_item']}  x{d['sale_qty']}\n"
        f"Unit Price: {d['sale_price']:.2f} {store['currency']}\n"
        f"Total: {total:.2f} {store['currency']}\n"
        f"Handling Fee: {d['sale_fee']:.2f} {store['currency']}\n"
        f"Note: {note or '—'}\n\nConfirm?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="sale_yes"),
         InlineKeyboardButton("❌ No",  callback_data="sale_no")]
    ])
    await update.message.reply_text(summary, reply_markup=kb)
    d["sale_note"] = note
    return S_CONFIRM


@require_unlock
async def confirm_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "sale_yes":
        await show_sales_menu(update, context)
        return ConversationHandler.END

    d = context.user_data
    cur = secure_db.table("stores").get(doc_id=d["sale_store"])["currency"]

    secure_db.insert("sales", {
        "customer_id": d["sale_customer"],
        "store_id":    d["sale_store"],
        "item_id":     d["sale_item"],
        "quantity":    d["sale_qty"],
        "unit_price":  d["sale_price"],
        "handling_fee":d["sale_fee"],
        "note":        d["sale_note"],
        "currency":    cur,
        "timestamp":   datetime.utcnow().isoformat(),
    })

    # deduct inventory
    q = Query()
    rec = secure_db.table("store_inventory").get((q.store_id == d["sale_store"]) & (q.item_id == d["sale_item"]))
    if rec:
        secure_db.update("store_inventory", {"quantity": rec["quantity"] - d["sale_qty"]}, [rec.doc_id])

    # credit handling fee
    if d["sale_fee"] > 0:
        secure_db.insert("store_payments", {
            "store_id": d["sale_store"],
            "amount":   d["sale_fee"],
            "currency": cur,
            "note":     "Handling fee for customer sale",
            "timestamp":datetime.utcnow().isoformat(),
        })

    await update.callback_query.edit_message_text(
        "✅ Sale recorded and inventory updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
    )
    return ConversationHandler.END


# ────────────────────────────────────────────────────────────────
#  EDIT FLOW – choose customer
# ────────────────────────────────────────────────────────────────
@require_unlock
async def edit_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = secure_db.all("customers")
    if not rows:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})",
                                    callback_data=f"edit_cust_{r.doc_id}") for r in rows]
    grid = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    grid.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text(
        "Select customer whose sales you want to edit:",
        reply_markup=InlineKeyboardMarkup(grid)
    )
    return S_EDIT_SELECT


async def get_edit_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    data = update.callback_query.data

    if data == "edit_time_back":
        return await edit_sale(update, context)

    cid = int(data.split("_")[-1])
    context.user_data.update({"edit_customer_id": cid, "edit_page": 1})

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Last 3 M", callback_data="edit_time_3m"),
         InlineKeyboardButton("📅 Last 6 M", callback_data="edit_time_6m")],
        [InlineKeyboardButton("🗓️ All",     callback_data="edit_time_all")],
        [InlineKeyboardButton("🔙 Back",    callback_data="edit_sale")],
    ])
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return S_EDIT_TIME


async def get_edit_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["edit_time_filter"] = update.callback_query.data.split("_")[-1]
    context.user_data["edit_page"] = 1
    return await send_edit_page(update, context)


async def send_edit_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = context.user_data["edit_customer_id"]
    period = context.user_data["edit_time_filter"]
    page   = context.user_data["edit_page"]
    size   = 20

    rows = [r for r in secure_db.all("sales") if r["customer_id"] == cid]
    if period == "3m":
        cut = datetime.utcnow().timestamp() - 90 * 86400
        rows = [r for r in rows if datetime.fromisoformat(r["timestamp"]).timestamp() >= cut]
    elif period == "6m":
        cut = datetime.utcnow().timestamp() - 180 * 86400
        rows = [r for r in rows if datetime.fromisoformat(r["timestamp"]).timestamp() >= cut]

    total_pages = max(1, (len(rows) + size - 1) // size)
    start, end  = (page - 1) * size, (page * size)
    chunk       = rows[start:end]

    if not chunk:
        await update.callback_query.edit_message_text(
            "No sales in that period.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="edit_sale")]])
        )
        return ConversationHandler.END

    lines = [f"{r.doc_id}: Store {r['store_id']}  Item {r['item_id']}  "
             f"x{r['quantity']} @ {r['unit_price']} ({r['currency']})"
             for r in chunk]
    text = (f"✏️ **Edit Sales**  Page {page}/{total_pages}\n\n" +
            "\n".join(lines) +
            "\n\nReply with the record **number** to edit, "
            "or use the buttons below.")

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="edit_prev"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="edit_next"))
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


# -- new: message with doc_id ---------------------------------------------
async def select_edit_sale_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = _extract_doc_id(update.message.text)
    if sid is None:
        await update.message.reply_text("Enter just the numeric record ID.")
        return S_EDIT_PAGE

    sale = secure_db.table("sales").get(doc_id=sid)
    cid  = context.user_data.get("edit_customer_id")
    if not sale or sale["customer_id"] != cid:
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
# -------------------------------------------------------------------------


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
                                        callback_data=f"edit_new_store_{s.doc_id}") for s in stores]
        rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
        rows.append([InlineKeyboardButton("🔙 Cancel", callback_data="edit_time_back")])
        await update.callback_query.edit_message_text("Select new store:", reply_markup=InlineKeyboardMarkup(rows))

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
    sid   = context.user_data["edit_sale_id"]
    field = context.user_data["edit_field"]
    new   = update.message.text.strip()
    context.user_data["new_value"] = new

    summary = (
        f"⚙️ **Confirm Edit**\nField: {field}\nNew value: {new}\n\nApply?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="edit_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="edit_conf_no")]
    ])
    await update.message.reply_text(summary, reply_markup=kb)
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

    if field == "store":
        secure_db.update("sales", {"store_id": int(new)}, [sid])
    elif field == "itemqty":
        item_id, qty = map(int, new.split(","))
        secure_db.update("sales", {"item_id": item_id, "quantity": qty}, [sid])
    elif field == "price":
        secure_db.update("sales", {"unit_price": float(new)}, [sid])
    elif field == "fee":
        secure_db.update("sales", {"handling_fee": float(new)}, [sid])
    elif field == "note":
        secure_db.update("sales", {"note": "" if new == "-" else new}, [sid])

    await update.callback_query.edit_message_text(
        "✅ Sale updated.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
    )
    return ConversationHandler.END


# ────────────────────────────────────────────────────────────────
#  DELETE FLOW – choose customer
# ────────────────────────────────────────────────────────────────
@require_unlock
async def delete_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = secure_db.all("customers")
    if not rows:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})",
                                    callback_data=f"del_cust_{r.doc_id}") for r in rows]
    grid = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    grid.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text(
        "Select customer whose sale you want to delete:",
        reply_markup=InlineKeyboardMarkup(grid)
    )
    return S_DELETE_SELECT


async def get_delete_customer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = int(update.callback_query.data.split("_")[-1])
    context.user_data.update({"delete_customer_id": cid})

    rows = [r for r in secure_db.all("sales") if r["customer_id"] == cid]
    if not rows:
        await update.callback_query.edit_message_text(
            "No sales for that customer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END

    lines = [f"{r.doc_id}: {r['item_id']} x{r['quantity']} @ {r['unit_price']}"
             for r in rows]
    msg = ("Reply with the record number to delete:\n\n" + "\n".join(lines))
    await update.callback_query.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
    )
    return S_DELETE_CONFIRM


# -- message with doc_id ---------------------------------------------------
async def select_delete_sale_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = _extract_doc_id(update.message.text)
    if sid is None:
        await update.message.reply_text("Enter just the numeric record ID.")
        return S_DELETE_CONFIRM

    sale = secure_db.table("sales").get(doc_id=sid)
    cid  = context.user_data.get("delete_customer_id")
    if not sale or sale["customer_id"] != cid:
        await update.message.reply_text("ID not found for that customer.")
        return S_DELETE_CONFIRM

    context.user_data.update({"del_sale": sale, "del_id": sid})
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="del_conf_yes"),
         InlineKeyboardButton("❌ No",  callback_data="del_conf_no")]
    ])
    await update.message.reply_text(
        f"Delete sale #{sid}?  Inventory will be restored.",
        reply_markup=kb
    )
    return S_DELETE_CONFIRM
# -------------------------------------------------------------------------


async def perform_delete_sale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if update.callback_query.data != "del_conf_yes":
        await show_sales_menu(update, context)
        return ConversationHandler.END

    sale = context.user_data["del_sale"]
    sid  = context.user_data["del_id"]

    # restore inventory
    q = Query()
    rec = secure_db.table("store_inventory").get((q.store_id == sale["store_id"]) & (q.item_id == sale["item_id"]))
    if rec:
        secure_db.update("store_inventory", {"quantity": rec["quantity"] + sale["quantity"]}, [rec.doc_id])

    # reverse handling fee
    if sale.get("handling_fee", 0) > 0:
        secure_db.insert("store_payments", {
            "store_id": sale["store_id"],
            "amount":  -sale["handling_fee"],
            "currency": sale["currency"],
            "note":     f"Reversal of fee for deleted sale #{sid}",
            "timestamp":datetime.utcnow().isoformat(),
        })

    secure_db.remove("sales", [sid])

    await update.callback_query.edit_message_text(
        f"✅ Sale #{sid} deleted and inventory/fee reversed.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
    )
    return ConversationHandler.END


# ────────────────────────────────────────────────────────────────
#  VIEW FLOW
# ────────────────────────────────────────────────────────────────
@require_unlock
async def view_sales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = secure_db.all("customers")
    if not rows:
        await update.callback_query.edit_message_text(
            "No customers.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="sales_menu")]])
        )
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(f"{r['name']} ({r['currency']})",
                                    callback_data=f"view_cust_{r.doc_id}") for r in rows]
    grid = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    grid.append([InlineKeyboardButton("🔙 Back", callback_data="sales_menu")])
    await update.callback_query.edit_message_text(
        "Select customer to view:",
        reply_markup=InlineKeyboardMarkup(grid)
    )
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
        [InlineKeyboardButton("🗓️ All",     callback_data="view_time_all")],
        [InlineKeyboardButton("🔙 Back",    callback_data="view_sales")],
    ])
    await update.callback_query.edit_message_text("Choose period:", reply_markup=kb)
    return S_VIEW_TIME


async def get_view_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data["view_time_filter"] = update.callback_query.data.split("_")[-1]
    context.user_data["view_page"] = 1
    return await send_sales_page(update, context)


async def send_sales_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = context.user_data["view_customer_id"]
    period = context.user_data["view_time_filter"]
    page   = context.user_data["view_page"]
    size   = 20

    rows = [r for r in secure_db.all("sales") if r["customer_id"] == cid]
    if period == "3m":
        cut = datetime.utcnow().timestamp() - 90 * 86400
        rows = [r for r in rows if datetime.fromisoformat(r["timestamp"]).timestamp() >= cut]
    elif period == "6m":
        cut = datetime.utcnow().timestamp() - 180 * 86400
        rows = [r for r in rows if datetime.fromisoformat(r["timestamp"]).timestamp() >= cut]

    total_pages = max(1, (len(rows) + size - 1) // size)
    start, end  = (page - 1) * size, (page * size)
    chunk       = rows[start:end]

    if not chunk:
        await update.callback_query.edit_message_text(
            "No sales in that period.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="view_sales")]])
        )
        return ConversationHandler.END

    lines = [f"{r.doc_id}: Store {r['store_id']}  Item {r['item_id']}  "
             f"x{r['quantity']} @ {r['unit_price']} ({r['currency']})"
             for r in chunk]
    text = f"📄 **Sales**  Page {page}/{total_pages}\n\n" + "\n".join(lines)

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="view_prev"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data="view_next"))
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


# ────────────────────────────────────────────────────────────────
#  CONVERSATION HANDLERS (Add / Edit / Delete / View)
# ────────────────────────────────────────────────────────────────
add_conv = ConversationHandler(
    entry_points=[CommandHandler("add_sale", add_sale),
                  CallbackQueryHandler(add_sale, pattern="^add_sale$")],
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
                        MessageHandler(filters.Regex(r"^\\d+$") & ~filters.COMMAND,
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
                           MessageHandler(filters.Regex(r"^\\d+$") & ~filters.COMMAND,
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


# ────────────────────────────────────────────────────────────────
#  REGISTER HANDLERS
# ────────────────────────────────────────────────────────────────
def register_sales_handlers(app):
    app.add_handler(CallbackQueryHandler(show_sales_menu, pattern="^sales_menu$"))
    app.add_handler(add_conv)
    app.add_handler(edit_conv)
    app.add_handler(delete_conv)
    app.add_handler(view_conv)
