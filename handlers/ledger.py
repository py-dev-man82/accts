# handlers/ledger.py

"""
Ledger module for accounting system.

Each entry records a financial or inventory-affecting event, for audit and reporting.
Ledger is append-only (historical), and all balances/reports are derived from these entries.
"""

import logging
from datetime import datetime
from secure_db import secure_db

logger = logging.getLogger("ledger")
LEDGER_TABLE = "ledger_entries"

def add_ledger_entry(
    account_type: str,
    account_id: int | str,
    entry_type: str,
    related_id: int | str | None,
    amount: float,
    currency: str,
    note: str = "",
    date: str | None = None,
    timestamp: str | None = None
):
    """
    Add a new entry to the ledger.

    Args:
        account_type:   "customer", "partner", "store", or "owner"
        account_id:     int or str (customer_id, partner_id, store_id, or "POT")
        entry_type:     "sale", "payment", "expense", "stockin", "payout", "fee", etc.
        related_id:     int or str, original doc_id of transaction (or None if not applicable)
        amount:         Signed float (credit +, debit -), in account's currency
        currency:       e.g. "USD", "GBP"
        note:           Free-form note
        date:           Optional: DDMMYYYY string. Defaults to today.
        timestamp:      Optional: ISO string. Defaults to now.
    """
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
    try:
        secure_db.insert(LEDGER_TABLE, entry)
        logger.info(f"Ledger entry added: {entry}")
    except Exception as e:
        logger.error(f"Failed to add ledger entry: {entry} | Error: {e}")

def get_ledger(account_type: str, account_id: int | str, start_date: str = None, end_date: str = None) -> list:
    """
    Get all ledger entries for an account, optionally filtered by date (DDMMYYYY).

    Returns: list of dicts, sorted oldest to newest.
    """
    try:
        rows = [r for r in secure_db.all(LEDGER_TABLE)
                if r["account_type"] == account_type and str(r["account_id"]) == str(account_id)]
    except Exception as e:
        logger.error(f"Failed to fetch ledger for {account_type}:{account_id} | Error: {e}")
        return []

    # Date filter if needed
    if start_date or end_date:
        def date_ok(row):
            try:
                d = datetime.strptime(row["date"], "%d%m%Y")
                if start_date:
                    d0 = datetime.strptime(start_date, "%d%m%Y")
                    if d < d0: return False
                if end_date:
                    d1 = datetime.strptime(end_date, "%d%m%Y")
                    if d > d1: return False
                return True
            except Exception as e:
                logger.error(f"Date parsing error in get_ledger: {row['date']} | Error: {e}")
                return False
        rows = [r for r in rows if date_ok(r)]

    rows.sort(key=lambda r: (r["date"], r["timestamp"]))  # oldest first
    return rows

def get_balance(account_type: str, account_id: int | str) -> float:
    """
    Get the current balance for an account (sum of all entries).
    """
    try:
        rows = get_ledger(account_type, account_id)
        balance = sum(r["amount"] for r in rows)
        return balance
    except Exception as e:
        logger.error(f"Failed to calculate balance for {account_type}:{account_id} | Error: {e}")
        return 0.0

def delete_ledger_entries_by_related(account_type: str, account_id: int | str, related_id: int | str):
    """
    Delete all ledger entries matching account_type, account_id, and related_id.
    Use for transaction deletions/rollbacks.
    """
    try:
        tbl = secure_db.table(LEDGER_TABLE)
        to_delete = [r.doc_id for r in tbl if r["account_type"] == account_type
                                            and str(r["account_id"]) == str(account_id)
                                            and str(r.get("related_id", "")) == str(related_id)]
        if to_delete:
            secure_db.remove(LEDGER_TABLE, to_delete)
            logger.info(f"Deleted ledger entries for related_id={related_id} ({account_type}:{account_id}): {to_delete}")
        else:
            logger.warning(f"No ledger entries found to delete for related_id={related_id} ({account_type}:{account_id})")
    except Exception as e:
        logger.error(f"Failed to delete ledger entries for related_id={related_id} ({account_type}:{account_id}) | Error: {e}")

def get_all_ledgers_for_type(account_type: str) -> dict:
    """
    Get all ledgers for a given account type.
    Returns: {account_id: [ledger entries]}
    """
    out = {}
    try:
        for r in secure_db.all(LEDGER_TABLE):
            if r["account_type"] != account_type:
                continue
            aid = str(r["account_id"])
            if aid not in out:
                out[aid] = []
            out[aid].append(r)
        # Sort each ledger
        for v in out.values():
            v.sort(key=lambda r: (r["date"], r["timestamp"]))
        return out
    except Exception as e:
        logger.error(f"Failed to get all ledgers for type {account_type} | Error: {e}")
        return {}
