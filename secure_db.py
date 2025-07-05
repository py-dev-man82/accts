# secure_db.py

import threading
import json
import base64
from datetime import datetime
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend

import config

# Auto-lock after this many seconds of inactivity
UNLOCK_TIMEOUT = 300

# 16-byte salt for key derivation (use your generated salt here)
KDF_SALT = b'\x9f\x8a\x17\xa4\x01\xbb\xcd\x23\x45\x67\x89\xab\xcd\xef\x01\x23'

class EncryptedJSONStorage(JSONStorage):
    """TinyDB storage that encrypts/decrypts the JSON blob via Fernet."""
    def __init__(self, path, fernet: Fernet, **kwargs):
        super().__init__(path, **kwargs)
        self.fernet = fernet

    def read(self):
        try:
            with open(self._handle, 'rb') as f:
                token = f.read()
            if not token:
                return {}
            data = self.fernet.decrypt(token)
            return json.loads(data.decode('utf-8'))
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def write(self, data):
        raw = json.dumps(data).encode('utf-8')
        token = self.fernet.encrypt(raw)
        with open(self._handle, 'wb') as f:
            f.write(token)

class SecureDB:
    """Encrypted TinyDB wrapper with optional encryption toggle."""
    def __init__(self, db_path):
        self.db_path     = db_path
        self._passphrase = None
        self.fernet      = None
        self.db          = None
        self._lock       = threading.Lock()
        self._timer      = None
        # starts locked or plain based on ENABLE_ENCRYPTION

    def _derive_fernet(self):
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=KDF_SALT,
            iterations=200_000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._passphrase))
        return Fernet(key)

    def unlock(self, passphrase: str = None):
        """Unlock or open the database. Passphrase required if encryption is enabled."""
        if not config.ENABLE_ENCRYPTION:
            # Plain JSON storage for testing
            self.db = TinyDB(self.db_path, storage=JSONStorage)
            return

        # Encrypted path
        if passphrase is None:
            raise ValueError("Passphrase is required to unlock encrypted DB.")
        with self._lock:
            self._passphrase = passphrase.encode('utf-8')
            self.fernet      = self._derive_fernet()
            self.db          = TinyDB(
                self.db_path,
                storage=lambda p: EncryptedJSONStorage(p, self.fernet)
            )
            self._reset_timer()

    def _reset_timer(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(UNLOCK_TIMEOUT, self.lock)
        self._timer.daemon = True
        self._timer.start()

    def lock(self):
        """Close and re-lock the database (no-op in testing mode)."""
        if not config.ENABLE_ENCRYPTION:
            return
        with self._lock:
            if self.db:
                self.db.close()
            self.db          = None
            self.fernet      = None
            self._passphrase = None

    def ensure_unlocked(self):
        """Raise if DB is not unlocked."""
        if not self.db:
            raise RuntimeError("🔒 Database is locked. Use /unlock <passphrase> first.")
        self._reset_timer()

    def table(self, name):
        self.ensure_unlocked()
        return self.db.table(name)

    def all(self, table_name):
        return self.table(table_name).all()

    def insert(self, table_name, doc):
        return self.table(table_name).insert(doc)

    def search(self, table_name, query):
        return self.table(table_name).search(query)

    def update(self, table_name, fields, doc_ids):
        self.table(table_name).update(fields, doc_ids=doc_ids)

    def remove(self, table_name, doc_ids):
        self.table(table_name).remove(doc_ids=doc_ids)

# Global instance
secure_db = SecureDB(config.DB_PATH)
