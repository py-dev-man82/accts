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
KDF_SALT = bytes.fromhex("9f8a17a401bbcd23456789abcdef0123")

class EncryptedJSONStorage(JSONStorage):
    def __init__(self, path, fernet: Fernet, **kwargs):
        super().__init__(path, **kwargs)
        self.fernet = fernet

    def read(self):
        try:
            text = self._handle.read()
            if not text:
                logger.error("❌ DB file exists but is empty.")
                raise RuntimeError("DB exists but is empty. Run /initdb to initialize.")
            token = base64.b64decode(text.encode('utf-8'))
            data = self.fernet.decrypt(token)
            logger.info("📥 DB decrypted successfully")
            return json.loads(data.decode('utf-8'))
        except InvalidToken:
            logger.error("🔒 Decryption failed: wrong key or corrupted DB")
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
                tables = self.db.tables()
                if not tables:
                    logger.error("❌ DB exists but is empty. Run /initdb.")
                    raise RuntimeError("DB is empty. Run /initdb.")
                self._unlocked = True
                self._last_access = time.monotonic()
                logger.info("✅ Database unlocked successfully")
            except RuntimeError as e:
                self._unlocked = False
                raise

    def lock(self):
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

    def get_last_access(self):
        return self._last_access

    def mark_activity(self):
        self._last_access = time.monotonic()
