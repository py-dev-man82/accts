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

# Auto-lock after inactivity (seconds)
UNLOCK_TIMEOUT = 300

# 16-byte salt in ASCII-escaped form
KDF_SALT = b'\x9f\x8a\x17\xa4\x01\xbb\xcd\x23\x45\x67\x89\xab\xcd\xef\x01\x23'

class EncryptedJSONStorage(JSONStorage):
    def __init__(self, path, fernet: Fernet, **kwargs):
        super().__init__(path, **kwargs)
        self.fernet = fernet

    def read(self):
        with open(self._handle, 'rb') as f:
            token = f.read()
        if not token:
            return {}
        data = self.fernet.decrypt(token)
        return json.loads(data.decode('utf-8'))

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

        # Test mode: open plain DB immediately
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
        if not config.ENABLE_ENCRYPTION:
            # No-op in test mode
            self.db = TinyDB(self.db_path, storage=JSONStorage)
            return

        with self._lock:
            self._passphrase = passphrase.encode('utf-8')
            self.fernet      = self._derive_fernet()
            self.db = TinyDB(
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
        if not config.ENABLE_ENCRYPTION:
            # No-op in test mode
            return
        with self._lock:
            if self.db:
                self.db.close()
            self.db          = None
            self.fernet      = None
            self._passphrase = None

    def ensure_unlocked(self):
        if not config.ENABLE_ENCRYPTION:
            return
        if self.db is None:
            raise RuntimeError("🔒 Database is locked. Use /unlock <passphrase> first.")
        self._reset_timer()

    def table(self, name):
        # No ensure here to simplify
        return self.db.table(name)

    def all(self, table_name):
        return self.db.table(table_name).all()

    def insert(self, table_name, doc):
        return self.db.table(table_name).insert(doc)

    def search(self, table_name, query):
        return self.db.table(table_name).search(query)

    def update(self, table_name, fields, doc_ids):
        self.db.table(table_name).update(fields, doc_ids=doc_ids)

    def remove(self, table_name, doc_ids):
        self.db.table(table_name).remove(doc_ids=doc_ids)

# Single shared instance
enable = config.ENABLE_ENCRYPTION
secure_db = SecureDB(config.DB_PATH)
