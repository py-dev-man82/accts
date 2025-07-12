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
KDF_SALT = bytes.fromhex("e62ee68733a7d9cfdfcc20b2e29c416c")


class EncryptedJSONStorage(JSONStorage):
    def __init__(self, path, fernet: Fernet, **kwargs):
        super().__init__(path, **kwargs)
        self.fernet = fernet

    def read(self):
        try:
            text = self._handle.read()
            if not text:
                logger.warning("📂 DB file is empty, returning {}")
                return {}
            token = base64.b64decode(text.encode('utf-8'))
            data = self.fernet.decrypt(token)
            logger.info("📥 DB decrypted successfully")
            return json.loads(data.decode('utf-8'))
        except FileNotFoundError:
            logger.warning("📄 DB file not found, starting fresh")
            return {}
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
        self.db_path         = db_path
        self._passphrase     = None
        self.fernet          = None
        self.db              = None
        self._unlocked       = False
        self._last_access    = 0
        self.failed_attempts = 0  # 🔥 Counter for failed unlocks

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
        """Unlock database or trigger security wipe on too many failed attempts."""
        if not config.ENABLE_ENCRYPTION:
            logger.info("🔓 Unlock called but encryption disabled")
            return

        # 🔥 Hardened wipe check BEFORE trying PIN
        if self.failed_attempts >= 7:
            logger.critical("💣 Too many failed attempts — wiping DB now!")
            self._wipe_database()
            raise RuntimeError("Database wiped after too many failed attempts.")

        logger.info("🔑 Attempting to unlock DB")
        self._passphrase = passphrase.encode('utf-8')
        self.fernet      = self._derive_fernet()

        try:
            self.db = TinyDB(
                self.db_path,
                storage=lambda p: EncryptedJSONStorage(p, self.fernet)
            )
            _ = self.db.tables()  # Trigger decryption
            self._unlocked = True
            self._last_access = time.monotonic()
            self.failed_attempts = 0  # ✅ Reset counter ONLY on success
            logger.info("✅ Database unlocked successfully")
        except RuntimeError as e:
            self.failed_attempts += 1
            attempts_left = 7 - self.failed_attempts
            logger.warning(f"❌ Unlock failed ({self.failed_attempts}/7). Attempts left: {attempts_left}")
            raise RuntimeError(f"Unlock failed: {e}")

    def lock(self):
        if not config.ENABLE_ENCRYPTION:
            logger.info("🔓 Lock called but encryption disabled")
            return
        if self.db:
            self.db.close()
        self.db          = None
        self.fernet      = None
        self._passphrase = None
        self._unlocked   = False
        logger.info("🔒 Database locked")

    def is_unlocked(self) -> bool:
        return self._unlocked

    def get_last_access(self):
        return self._last_access

    def mark_activity(self):
        self._last_access = time.monotonic()

    def _wipe_database(self):
        """Security wipe: delete DB file and reset counter."""
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                logger.critical("💣 Database file wiped after 7 failed unlock attempts!")
            self.failed_attempts = 0
            self.lock()
        except Exception as e:
            logger.error(f"❌ Error wiping database: {e}")
            raise

    # Usual TinyDB wrappers...
    def table(self, name): ...
    def insert(self, table_name, doc): ...
    def all(self, table_name): ...
    def search(self, table_name, query): ...
    def update(self, table_name, fields, doc_ids): ...
    def remove(self, table_name, doc_ids): ...


# Global instance
secure_db = SecureDB(config.DB_PATH)
