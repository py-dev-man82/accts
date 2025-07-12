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
UNLOCK_TIMEOUT = 18000  # 3 minutes
KDF_SALT = bytes.fromhex("9f8a17a401bbcd23456789abcdef0123")

class EncryptedJSONStorage(JSONStorage):
    def __init__(self, path, fernet: Fernet, **kwargs):
        super().__init__(path, **kwargs)
        self.fernet = fernet

    def read(self):
        try:
            text = self._handle.read()
            if not text:
                logger.warning("📂 DB file is empty, returning {}")
                return {}  # ✅ Allow empty DB for initial seeding
            token = base64.b64decode(text.encode('utf-8'))
            data = self.fernet.decrypt(token)
            logger.info("📥 DB decrypted successfully")
            return json.loads(data.decode('utf-8'))
        except InvalidToken:
            logger.error("🔒 Decryption failed: wrong key or unencrypted DB")
            raise RuntimeError("Failed to decrypt DB. Wrong PIN or unencrypted?")
        except Exception as e:
            logger.exception("❌ Unexpected error while reading DB")
            raise RuntimeError("Failed to read DB file") from e

    def write(self, data):
        raw = json.dumps(data).encode('utf-8')
        token = self.fernet.encrypt(raw)
        text = base64.b64encode(token).decode('utf-8')
        self._handle.write(text)
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
            logger.error("❌ Encryption disabled. Refusing to continue.")
            raise RuntimeError("Encryption must be enabled in config.py.")

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
            raise RuntimeError("Encryption disabled. Cannot unlock DB.")

        with self._lock:
            logger.info("🔑 Attempting to unlock DB")
            self._passphrase = passphrase.encode('utf-8')
            self.fernet      = self._derive_fernet()

            if not os.path.exists(self.db_path):
                logger.error("❌ DB file does not exist. Run /initdb first.")
                raise RuntimeError("DB not found. Run /initdb to create.")

            try:
                self.db = TinyDB(
                    self.db_path,
                    storage=lambda p: EncryptedJSONStorage(p, self.fernet)
                )

                # 🛡 Validate: ensure system table exists if DB has data
                tables = self.db.tables()
                if tables and "system" not in tables:
                    logger.error("❌ DB decrypted but no system table found. Wrong PIN?")
                    raise RuntimeError("Failed to validate PIN: system table missing.")

                logger.info("✅ Database unlocked successfully")
                self._unlocked = True
                self._last_access = time.monotonic()

            except InvalidToken:
                logger.error("❌ Decryption failed: wrong PIN")
                self._unlocked = False
                raise RuntimeError("❌ Wrong PIN or corrupted DB.")

            except Exception as e:
                logger.exception("❌ Unexpected error while unlocking DB")
                self._unlocked = False
                raise RuntimeError(f"Unlock failed: {e}")

    def lock(self):
        with self._lock:
            if self.db:
                self.db.close()
            self.db          = None
            self.fernet      = None
            self._passphrase = None
            self._unlocked   = False
            logger.info("🔒 Database locked")

    def has_pin(self) -> bool:
    """
    Check if the DB has been initialized with a PIN (system table exists).
    """
    if not os.path.exists(self.db_path):
        logger.info("📂 No DB file found, no PIN set.")
        return False

    try:
        temp_db = TinyDB(
            self.db_path,
            storage=lambda p: EncryptedJSONStorage(p, self._derive_fernet())
        )
        tables = temp_db.tables()
        temp_db.close()
        has_system = "system" in tables
        logger.info(f"📋 DB has PIN: {has_system}")
        return has_system
    except Exception:
        logger.warning("⚠️ Could not verify PIN (probably uninitialized).")
        return False

    def is_unlocked(self) -> bool:
        return self._unlocked

    def get_last_access(self):
        return self._last_access

    def mark_activity(self):
        self._last_access = time.monotonic()

    def table(self, name):
        """Proxy to TinyDB.table() with unlock check."""
        self.ensure_unlocked()
        logger.debug(f"📂 Accessing table: {name}")
        return self.db.table(name)

    def ensure_unlocked(self):
        if not self._unlocked:
            logger.warning("🔒 DB access attempted while locked")
            raise RuntimeError("🔒 Database is locked. Please /unlock first.")

# Global instance
secure_db = SecureDB(config.DB_PATH)

# ✅ Export for external use
__all__ = ["secure_db", "EncryptedJSONStorage", "SecureDB"]
