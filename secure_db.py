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
            logger.error("❌ Encryption must be enabled. Refusing to load plaintext DB.")
            raise RuntimeError("Encryption disabled. Set ENABLE_ENCRYPTION = True in config.py.")

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
            logger.error("❌ Encryption disabled. Cannot unlock DB.")
            raise RuntimeError("Encryption is disabled. Cannot unlock DB.")

        with self._lock:
            logger.info("🔑 Attempting to unlock DB")
            self._passphrase = passphrase.encode('utf-8')
            self.fernet      = self._derive_fernet()

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

            # Try to open encrypted DB and validate PIN
            try:
                self.db = TinyDB(
                    self.db_path,
                    storage=lambda p: EncryptedJSONStorage(p, self.fernet)
                )
                _ = self.db.tables()  # Force decryption
                self._unlocked = True
                self._last_access = time.monotonic()
                logger.info("✅ Database unlocked successfully")
            except RuntimeError:
                logger.error("❌ Unlock failed: wrong PIN or corrupted DB")
                self._unlocked = False
                raise RuntimeError("❌ Wrong PIN or corrupted DB.")

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

    def get_last_access(self):
        return self._last_access

    def mark_activity(self):
        self._last_access = time.monotonic()
