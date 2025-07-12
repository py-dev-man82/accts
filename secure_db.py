# secure_db.py

import threading
import json
import base64
import os
import time
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend

import config

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
            with open(self._handle, 'rb') as f:
                token = f.read()
            if not token:
                return {}
            data = self.fernet.decrypt(token)
            return json.loads(data.decode('utf-8'))
        except FileNotFoundError:
            return {}
        except InvalidToken:
            raise RuntimeError("🔒 Decryption failed: Wrong key or unencrypted DB.")
        except Exception as e:
            raise RuntimeError("🔒 Failed to decrypt DB file.") from e

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
        self._unlocked   = False
        self._last_access= 0

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
            return

        with self._lock:
            self._passphrase = passphrase.encode('utf-8')
            self.fernet      = self._derive_fernet()

            try:
                # Try to open encrypted DB
                self.db = TinyDB(
                    self.db_path,
                    storage=lambda p: EncryptedJSONStorage(p, self.fernet)
                )
                _ = self.db.tables()  # Force decryption
                self._unlocked = True
                self._last_access = time.monotonic()
                print("✅ Database unlocked (encrypted).")
            except RuntimeError as e:
                # If decryption fails, check if DB is plaintext
                if "unencrypted" in str(e).lower():
                    print("⚠️ Plaintext DB detected. Migrating to encrypted format…")
                    self._migrate_plaintext_to_encrypted()
                    self._unlocked = True
                    self._last_access = time.monotonic()
                    print("✅ Migration complete. Database now encrypted.")
                else:
                    self._unlocked = False
                    raise

    def _migrate_plaintext_to_encrypted(self):
        # Load plaintext DB
        plaintext_db = TinyDB(self.db_path, storage=JSONStorage)
        all_data = {}
        for table in plaintext_db.tables():
            all_data[table] = plaintext_db.table(table).all()
        plaintext_db.close()

        # Recreate DB encrypted
        self.db = TinyDB(
            self.db_path,
            storage=lambda p: EncryptedJSONStorage(p, self.fernet)
        )
        for table_name, rows in all_data.items():
            tbl = self.db.table(table_name)
            for row in rows:
                tbl.insert(row)

    def lock(self):
        if not config.ENABLE_ENCRYPTION:
            return
        with self._lock:
            if self.db:
                self.db.close()
            self.db          = None
            self.fernet      = None
            self._passphrase = None
            self._unlocked   = False
            print("🔒 Database locked.")

    def is_unlocked(self) -> bool:
        return self._unlocked

    def needs_unlock(self) -> bool:
        return config.ENABLE_ENCRYPTION and not self._unlocked

    def ensure_unlocked(self):
        if config.ENABLE_ENCRYPTION and not self.is_unlocked():
            raise RuntimeError("🔒 Database is locked. Please /unlock first.")
        if config.ENABLE_ENCRYPTION and self._unlocked:
            now = time.monotonic()
            if now - self._last_access > UNLOCK_TIMEOUT:
                self.lock()
                raise RuntimeError("🔒 Auto-locked after inactivity. Please /unlock again.")
            self._last_access = now

    def mark_activity(self):
        self._last_access = time.monotonic()

    def table(self, name):
        self.ensure_unlocked()
        return self.db.table(name)

    def all(self, table_name):
        self.ensure_unlocked()
        return self.db.table(table_name).all()

    def insert(self, table_name, doc):
        self.ensure_unlocked()
        return self.db.table(table_name).insert(doc)

    def search(self, table_name, query):
        self.ensure_unlocked()
        return self.db.table(table_name).search(query)

    def update(self, table_name, fields, doc_ids):
        self.ensure_unlocked()
        return self.db.table(table_name).update(fields, doc_ids=doc_ids)

    def remove(self, table_name, doc_ids):
        self.ensure_unlocked()
        return self.db.table(table_name).remove(doc_ids=doc_ids)

# Global instance
secure_db = SecureDB(config.DB_PATH)
