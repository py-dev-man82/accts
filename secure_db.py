import os
import json
import base64
import logging
import time
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.fernet import Fernet, InvalidToken

DB_FILE = "data/db.json"
SALT_FILE = "data/kdf_salt.bin"
MAX_PIN_ATTEMPTS = 7

logger = logging.getLogger("secure_db")
logger.setLevel(logging.INFO)

class EncryptedJSONStorage(JSONStorage):
    def __init__(self, path, fernet: Fernet, **kwargs):
        super().__init__(path, **kwargs)
        self.fernet = fernet

    def read(self):
        logger.info("READ CALLED")
        try:
            if not os.path.exists(self._storage_path):
                logger.warning("📂 DB file does not exist, returning {}")
                return {}
            with open(self._storage_path, "r", encoding="utf-8") as f:
                raw = f.read()
            if not raw:
                logger.warning("📂 DB file is empty, returning {}")
                return {}
            token = base64.urlsafe_b64decode(raw.encode())
            decrypted = self.fernet.decrypt(token)
            return json.loads(decrypted.decode())
        except InvalidToken:
            logger.error("🔒 Decryption failed: wrong key or unencrypted DB")
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected error while reading DB: {e}")
            raise

    def write(self, data):
        logger.info("WRITE CALLED")
        try:
            json_str = json.dumps(data, separators=(",", ":")).encode()
            token = self.fernet.encrypt(json_str)
            encoded = base64.urlsafe_b64encode(token).decode()
            with open(self._storage_path, "w", encoding="utf-8") as f:
                f.seek(0)
                f.truncate()
                f.write(encoded)
                f.flush()
            logger.info("💾 DB written and encrypted successfully")
        except Exception as e:
            logger.error(f"❌ Failed to write DB: {e}")
            raise

class SecureDB:
    def __init__(self):
        self.db = None
        self.fernet = None
        self._passphrase = None
        self._unlocked = False
        self._failed_attempts = 0
        self._last_access = time.monotonic()

    def _load_salt(self):
        if not os.path.exists(SALT_FILE):
            raise RuntimeError(
                f"KDF salt file missing: {SALT_FILE}. "
                "Run setup_secure_db.sh to create a new salt before /initdb."
            )
        salt = open(SALT_FILE, "rb").read()
        logger.debug(f"🔑 Loaded existing KDF salt ({len(salt)} bytes)")
        return salt

    def _derive_key(self, pin: str) -> Fernet:
        salt = self._load_salt()
        kdf = Scrypt(
            salt=salt,
            length=32,
            n=2**14,
            r=8,
            p=1,
        )
        key = kdf.derive(pin.encode("utf-8"))
        token = base64.urlsafe_b64encode(key)
        logger.debug(f"🔑 Derived encryption key from PIN and salt")
        return Fernet(token)

    def unlock(self, pin: str) -> bool:
        if self._unlocked:
            logger.info("🔓 Database already unlocked")
            return True

        self.fernet = self._derive_key(pin)
        try:
            self.db = TinyDB(
                DB_FILE,
                storage=lambda p: EncryptedJSONStorage(p, self.fernet),
            )
            _ = self.db.all()
            logger.info("✅ Database unlocked successfully")
            self._passphrase = pin
            self._unlocked = True
            self._failed_attempts = 0
            self._last_access = time.monotonic()
            return True
        except Exception as e:
            self._failed_attempts += 1
            logger.error(f"❌ Unlock failed ({self._failed_attempts}/{MAX_PIN_ATTEMPTS}): {e}")
            if self._failed_attempts >= MAX_PIN_ATTEMPTS:
                logger.critical("☠️ Maximum PIN attempts exceeded. Wiping DB and salt!")
                self._wipe_db()
            return False

    def lock(self):
        if self._unlocked and self.db is not None:
            self.db.close()
            self._unlocked = False
            logger.info("🔒 Database locked")

    def is_unlocked(self) -> bool:
        return self._unlocked

    def has_pin(self) -> bool:
        return os.path.exists(DB_FILE) and os.path.exists(SALT_FILE)

    def _wipe_db(self):
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            logger.warning("🗑️ DB file deleted")
        if os.path.exists(SALT_FILE):
            try:
                os.chmod(SALT_FILE, 0o666)  # Make salt writable before deleting
            except Exception as e:
                logger.warning(f"Could not change salt file permissions: {e}")
            os.remove(SALT_FILE)
            logger.warning("🗑️ Salt file deleted")
        self._passphrase = None
        self._unlocked = False
        self._failed_attempts = 0
        logger.critical("💥 Database and salt wiped due to security policy")

    def mark_activity(self):
        self._last_access = time.monotonic()

    def get_last_access(self):
        return self._last_access

    # ===== Pass-through TinyDB methods for use in handlers =====

    def insert(self, table, doc):
        self.ensure_unlocked()
        result = self.db.table(table).insert(doc)
        self.db.close()  # force write to disk
        self.unlock(self._passphrase)  # re-open for next access
        return result

    def all(self, table):
        self.ensure_unlocked()
        return self.db.table(table).all()

    def search(self, table, cond):
        self.ensure_unlocked()
        return self.db.table(table).search(cond)

    def update(self, table, fields, cond):
        self.ensure_unlocked()
        result = self.db.table(table).update(fields, cond)
        self.db.close()
        self.unlock(self._passphrase)
        return result

    def remove(self, table, cond):
        self.ensure_unlocked()
        result = self.db.table(table).remove(cond)
        self.db.close()
        self.unlock(self._passphrase)
        return result

    def get(self, table, cond):
        self.ensure_unlocked()
        return self.db.table(table).get(cond)

    def ensure_unlocked(self):
        if not self._unlocked:
            raise RuntimeError("🔒 Database is locked. Unlock it first.")

secure_db = SecureDB()
