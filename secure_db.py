# secure_db.py

import threading
import json
import base64
import os
import time
import logging
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend

import config

logger = logging.getLogger("secure_db")
logger.setLevel(logging.INFO)

# Auto-lock timeout in seconds
UNLOCK_TIMEOUT = 180  # 3 minutes
SALT_HEX = "9f8a17a401bbcd23456789abcdef0123"
KDF_SALT = bytes.fromhex(SALT_HEX)

class EncryptedJSONStorage(JSONStorage):
    def __init__(self, path, fernet: Fernet, **kwargs):
        super().__init__(path, **kwargs)
        self.fernet = fernet

    def read(self):
        try:
            text = self._handle.read()  # Read as text
            if not text:
                logger.info("📂 DB file is empty, returning {}")
                return {}
            token = base64.b64decode(text.encode('utf-8'))  # Base64 decode → bytes
            data = self.fernet.decrypt(token)
            logger.info("📥 DB decrypted successfully")
            return json.loads(data.decode('utf-8'))
        except FileNotFoundError:
            logger.warning("📄 DB file not found, starting fresh")
            return {}
        except InvalidToken:
            logger.error("🔒 Decryption failed: wrong key or unencrypted DB")
            raise RuntimeError("Failed to decrypt DB. Wrong key or unencrypted?")
        except Exception as e:
            logger.exception("❌ Unexpected error while reading DB")
            raise RuntimeError("Failed to read DB file") from e

    def write(self, data):
        raw = json.dumps(data).encode('utf-8')
        token = self.fernet.encrypt(raw)  # Encrypted bytes
        text = base64.b64encode(token).decode('utf-8')  # Encode as Base64 string
        self._handle.write(text)  # Write as text
        logger.info("💾 DB written and encrypted successfully")

class SecureDB:
    def __init__(self, db_path):
        self.db_path     = db_path
        self._passphrase = None
        self.fernet      = None
        self.db          = None
        self._lock       = threading.Lock()
        self._unlocked   = False
        self._last_access= 0

        if not config.ENABLE_ENCRYPTION:
            self.db = TinyDB(self.db_path, storage=JSONStorage)
            logger.info("🔓 Encryption disabled: using plaintext DB")

    def _derive_fernet(self):
        logger.debug("🔑 Deriving encryption key from passphrase")
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=KDF_SALT,
            iterations=200_000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._passphrase))
        return Fernet(key)

    def unlock(self, passphrase: str):
        if not config.ENABLE_ENCRYPTION:
            logger.info("🔓 Unlock called but encryption disabled")
            return

        with self._lock:
            logger.info("🔑 Attempting to unlock DB")
            self._passphrase = passphrase.encode('utf-8')
            self.fernet      = self._derive_fernet()

            try:
                if not os.path.exists(self.db_path):
                    # No DB file yet → initialize encrypted DB
                    logger.warning("📄 No DB file found. Creating new encrypted DB.")
                    self.db = TinyDB(
                        self.db_path,
                        storage=lambda p: EncryptedJSONStorage(p, self.fernet)
                    )
                    self._unlocked = True
                    self._last_access = time.monotonic()
                    logger.info("✅ New encrypted DB initialized.")
                    return

                # Try to open encrypted DB
                self.db = TinyDB(
                    self.db_path,
                    storage=lambda p: EncryptedJSONStorage(p, self.fernet)
                )
                _ = self.db.tables()  # Trigger decryption
                self._unlocked = True
                self._last_access = time.monotonic()
                logger.info("✅ Database unlocked successfully")
            except RuntimeError as e:
                if "unencrypted" in str(e).lower():
                    logger.warning("⚠️ Plaintext DB detected, migrating to encrypted format")
                    self._migrate_plaintext_to_encrypted()
                    self._unlocked = True
                    self._last_access = time.monotonic()
                    logger.info("✅ Migration complete: DB now encrypted")
                else:
                    self._unlocked = False
                    logger.error(f"❌ Unlock failed: {e}")
                    raise

    def _migrate_plaintext_to_encrypted(self):
        plaintext_db = TinyDB(self.db_path, storage=JSONStorage)
        all_data = {}
        for table in plaintext_db.tables():
            all_data[table] = plaintext_db.table(table).all()
        plaintext_db.close()
        logger.info(f"📦 Migrating {len(all_data)} tables to encrypted DB")
        self.db = TinyDB(
            self.db_path,
            storage=lambda p: EncryptedJSONStorage(p, self.fernet)
        )
        for table_name, rows in all_data.items():
            tbl = self.db.table(table_name)
            for row in rows:
                tbl.insert(row)
        logger.info("✅ Data migration completed")

    def lock(self):
        if not config.ENABLE_ENCRYPTION:
            logger.info("🔓 Lock called but encryption disabled")
            return
        with self._lock:
            if self.db:
                self.db.close()
            self.db          = None
            self.fernet      = None
            self._passphrase = None
            self._unlocked   = False
            logger.info("🔒 Database locked")

    def is_unlocked(self) -> bool:
        return self._unlocked

    def needs_unlock(self) -> bool:
        return config.ENABLE_ENCRYPTION and not self._unlocked

    def ensure_unlocked(self):
        if config.ENABLE_ENCRYPTION and not self.is_unlocked():
            logger.warning("🔒 DB access attempted while locked")
            raise RuntimeError("🔒 Database is locked. Please /unlock first.")
        if config.ENABLE_ENCRYPTION and self._unlocked:
            now = time.monotonic()
            if now - self._last_access > UNLOCK_TIMEOUT:
                logger.warning("⏳ Auto-lock timeout reached, locking DB")
                self.lock()
                raise RuntimeError("🔒 Auto-locked after inactivity. Please /unlock again.")
            self._last_access = now

    def mark_activity(self):
        self._last_access = time.monotonic()

    def table(self, name):
        self.ensure_unlocked()
        logger.debug(f"📂 Accessing table: {name}")
        return self.db.table(name)

    def all(self, table_name):
        self.ensure_unlocked()
        logger.info(f"📄 Reading all rows from table: {table_name}")
        return self.db.table(table_name).all()

    def insert(self, table_name, doc):
        self.ensure_unlocked()
        logger.info(f"➕ Inserting into table {table_name}: {doc}")
        return self.db.table(table_name).insert(doc)

    def search(self, table_name, query):
        self.ensure_unlocked()
        logger.debug(f"🔍 Searching in table {table_name}")
        return self.db.table(table_name).search(query)

    def update(self, table_name, fields, doc_ids):
        self.ensure_unlocked()
        logger.info(f"✏️ Updating table {table_name} on doc_ids {doc_ids}: {fields}")
        return self.db.table(table_name).update(fields, doc_ids=doc_ids)

    def remove(self, table_name, doc_ids):
        self.ensure_unlocked()
        logger.info(f"🗑️ Removing from table {table_name} doc_ids {doc_ids}")
        return self.db.table(table_name).remove(doc_ids=doc_ids)

# Global instance
secure_db = SecureDB(config.DB_PATH) 
