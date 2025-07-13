# handlers/ledger.py
"""
Ledger module for accounting system.

Each entry records a financial or inventory-affecting event, for audit and reporting.
Ledger is append-only (historical), and all balances/reports are derived from these entries.

Now supports optional: item_id, quantity, unit_price, store_id, fee_perc, fee_amt, fx_rate, usd_amt.
"""

import logging
import inspect
from datetime import datetime
from secure_db import secure_db

logger = logging.getLogger("ledger")

# ─── if the parent application hasn’t configured us, do it here ──────────
if not logger.hasHandlers():
    logger.setLevel(logging.DEBUG)
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s — %(name)s — %(levelname)s — %(message)s"))
    logger.addHandler(_h)

LEDGER_TABLE = "ledger_entries"


# ─────────────────────────────────────────────────────────────────────────
#  DB bootstrap
# ─────────────────────────────────────────────────────────────────────────
def seed_tables(secure_db):
    """
    Seed minimal tables into DB after /initdb to ensure DB is never empty.
    """
    logger.info("📥 Seeding initial tables…")
    try:
        # Seed 'system' metadata table
        system_table = secure_db.db.table("system")
        system_table.insert({
            "version": 1,
            "initialized": True,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Create empty ledger, transactions, and accounts tables
        secure_db.db.table(LEDGER_TABLE)
        secure_db.db.table("transactions")
        secure_db.db.table("accounts")

        logger.info("✅ Initial tables seeded successfully.")
    except Exception as e:
        logger.exception("❌ Failed to seed initial tables")


# ─────────────────────────────────────────────────────────────────────────
#  Writer
# ─────────────────────────────────────────────────────────────────────────
def add_ledger_entry(
    account_type: str,
    account_id: int | str,
    entry_type: str,
    related_id: int | str | None,
    amount: float,
    currency: str,
    note: str = "",
    date: str | None = None,
    timestamp: str | None = None,
    item_id: str | int | None = None,
    quantity: int | None = None,
    unit_price: float | None = None,
    store_id: int | str | None = None,
    fee_perc: float | None = None,
    fee_amt: float | None = None,
    fx_rate: float | None = None,
    usd_amt: float | None = None,
):
    """
    Add a new entry to the ledger.
    """
    caller = inspect.stack()[1]
    logger.debug(
        "📨 add_ledger_entry called from %s:%s (%s)",
        os.path.basename(caller.filename),
        caller.lineno,
        caller.function,
    )
    logger.debug(
        "Arguments → acct=%s id=%s type=%s rel=%s amt=%s cur=%s",
        account_type,
        account_id,
        entry_type,
        related_id,
        amount,
        currency,
    )

    if date is None:
        date = datetime.now().strftime("%d%m%Y")
    if timestamp is None:
        timestamp = datetime.utcnow().isoformat()

    entry = {
        "account_type": account_type,
        "account_id":   account_id,
        "entry_type":   entry_type,
        "related_id":   related_id,
        "amount":       amount,
        "currency":     currency,
        "note":         note,
        "date":         date,
        "timestamp":    timestamp,
    }
    # Add expanded optional fields if supplied
    if item_id   is not None: entry["item_id"]   = item_id
    if quantity  is not None: entry["quantity"]  = quantity
    if unit_price is not None: entry["unit_price"] = unit_price
    if store_id  is not None: entry["store_id"]  = store_id
    if fee_perc  is not None: entry["fee_perc"]  = fee_perc
    if fee_amt   is not None: entry["fee_amt"]   = fee_amt
    if fx_rate   is not None: entry["fx_rate"]   = fx_rate
    if usd_amt   is not None: entry["usd_amt"]   = usd_amt

    logger.debug("Payload to persist: %s", entry)

    try:
        doc_id = secure_db.insert(LEDGER_TABLE, entry)
        logger.info("📝 Ledger entry #%s saved.", doc_id)
        return doc_id
    except Exception:
        logger.exception("❌ Failed inserting ledger entry")


# ─────────────────────────────────────────────────────────────────────────
#  Readers
# ─────────────────────────────────────────────────────────────────────────
def get_ledger(account_type: str,
               account_id: int | str,
               start_date: str | None = None,
               end_date: str | None = None) -> list:
    """
    Get all ledger entries for an account, optionally filtered by date (DDMMYYYY).
    """
    logger.debug("Fetching ledger rows for %s:%s", account_type, account_id)
    try:
        rows = [
            r for r in secure_db.all(LEDGER_TABLE)
            if r["account_type"] == account_type
            and str(r["account_id"]) == str(account_id)
        ]
    except Exception:
        logger.exception("Failed to fetch ledger")
        return []

    # Date filter if needed
    if start_date or end_date:
        def in_range(row):
            try:
                d = datetime.strptime(row["date"], "%d%m%Y")
                if start_date and d < datetime.strptime(start_date, "%d%m%Y"):
                    return False
                if end_date and d > datetime.strptime(end_date, "%d%m%Y"):
                    return False
                return True
            except Exception:
                logger.exception("Bad date in row %s", row)
                return False
        rows = [r for r in rows if in_range(r)]

    rows.sort(key=lambda r: (r["date"], r["timestamp"]))
    logger.debug("Retrieved %d rows", len(rows))
    return rows


def get_balance(account_type: str, account_id: int | str) -> float:
    try:
        bal = sum(r["amount"] for r in get_ledger(account_type, account_id))
        logger.debug("Balance for %s:%s ⇒ %s", account_type, account_id, bal)
        return bal
    except Exception:
        logger.exception("Balance calc failed")
        return 0.0


# ─────────────────────────────────────────────────────────────────────────
#  Deleter
# ─────────────────────────────────────────────────────────────────────────
def delete_ledger_entries_by_related(account_type: str,
                                     account_id: int | str,
                                     related_id: int | str):
    """
    Delete all ledger entries matching account_type, account_id, related_id.
    """
    logger.debug("Deleting ledger rows for rel=%s (%s:%s)",
                 related_id, account_type, account_id)
    try:
        tbl = secure_db.table(LEDGER_TABLE)
        to_delete = [
            r.doc_id for r in tbl
            if r["account_type"] == account_type
            and str(r["account_id"]) == str(account_id)
            and str(r.get("related_id", "")) == str(related_id)
        ]
        if to_delete:
            secure_db.remove(LEDGER_TABLE, to_delete)
            logger.info("🗑️ Removed ledger rows %s", to_delete)
        else:
            logger.warning("No ledger rows matched (nothing removed)")
    except Exception:
        logger.exception("Ledger delete failed")
