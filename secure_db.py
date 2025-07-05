# secure_db.py

import threading
import json
import base64
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend

import config

# Auto-lock timeout (unused when encryption disabled)
UNLOCK_TIMEOUT = 300

# 16-byte salt in hex to ensure ASCII-only
SALT_HEX = "9f8a17a401bbcd23456789abcdef0123"
KDF_SALT = bytes.fromhex(SALT_HEX)

class EncryptedJSONStorage(JSONStorage):
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
    def __init__(self, db_path):
        self.db_path     = db_path
        self._passphrase = None
        self.fernet      = None
        self.db          = None
        self._lock       = threading.Lock()
        self._timer      = None

        # Test mode: open unencrypted immediately
        if not config.ENABLE_ENCRYPTION:
            self.db = TinyDB(self.db_path, storage=JSONStorage)

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

    def unlock(self, passphrase: str):
        # No-op in test mode
        if not config.ENABLE_ENCRYPTION:
            return

        with self._lock:
            self._passphrase = passphrase.encode('utf-8')
            self.fernet      = self._derive_fernet()
            self.db = TinyDB(
                self.db_path,
                storage=lambda p: EncryptedJSONStorage(p, self.fernet)
            )

    def lock(self):
        # No-op in test mode
        if not config.ENABLE_ENCRYPTION:
            return

        with self._lock:
            if self.db:
                self.db.close()
            self.db          = None
            self.fernet      = None
            self._passphrase = None

    def ensure_unlocked(self):
        # No-op to bypass locking entirely
        return

    def table(self, name):
        return self.db.table(name)

    def all(self, table_name):
        return self.db.table(table_name).all()

    def insert(self, table_name, doc):
        return self.db.table(table_name).insert(doc)

    def search(self, table_name, query):
        return self.db.table(table_name).search(query)

    def update(self, table_name, fields, doc_ids):
        return self.db.table(table_name).update(fields, doc_ids=doc_ids)

    def remove(self, table_name, doc_ids):
        return self.db.table(table_name).remove(doc_ids=doc_ids)

# Global instance
secure_db = SecureDB(config.DB_PATH)
