# secure_db.py

import threading, json
from time import time
from datetime import datetime
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
import base64

# Configuration for auto-lock timeout and key derivation salt
UNLOCK_TIMEOUT = 300  # seconds of inactivity before auto-lock
KDF_SALT      = b'your-static-salt-here'  # replace with a secure random salt

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
    def __init__(self, db_path, passphrase: str):
        self.db_path = db_path
        self.passphrase = passphrase.encode('utf-8')
        self.fernet = None
        self.db = None
        self._lock = threading.Lock()
        self._timer = None
        self.unlock()

    def _derive_key(self):
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=KDF_SALT,
            iterations=200_000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.passphrase))
        return Fernet(key)

    def unlock(self):
        with self._lock:
            self.fernet = self._derive_key()
            self.db = TinyDB(self.db_path,
                             storage=lambda p: EncryptedJSONStorage(p, self.fernet))
            self._reset_timer()

    def _reset_timer(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(UNLOCK_TIMEOUT, self.lock)
        self._timer.daemon = True
        self._timer.start()

    def lock(self):
        with self._lock:
            if self.db:
                self.db.close()
            self.db = None
            self.fernet = None

    def ensure_unlocked(self):
        if not self.db:
            raise RuntimeError("🔒 Database is locked. Use /unlock first.")
        self._reset_timer()

    def table(self, name):
        self.ensure_unlocked()
        return self.db.table(name)

    def all(self, table_name):
        return self.table(table_name).all()

    def insert(self, table_name, doc):
        tbl = self.table(table_name)
        return tbl.insert(doc)

    def search(self, table_name, query):
        tbl = self.table(table_name)
        return tbl.search(query)

    def update(self, table_name, fields, doc_ids):
        tbl = self.table(table_name)
        tbl.update(fields, doc_ids=doc_ids)

    def remove(self, table_name, doc_ids):
        tbl = self.table(table_name)
        tbl.remove(doc_ids=doc_ids)
