import os
import json
import base64
import logging
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.fernet import Fernet, InvalidToken

# Config
DB_FILE = "data/db.json"
SALT_FILE = "data/kdf_salt.bin"
MAX_PIN_ATTEMPTS = 7

# Logger
logger = logging.getLogger("secure_db")
logger.setLevel(logging.INFO)

class EncryptedJSONStorage(JSONStorage):
    """Custom TinyDB storage with encryption."""
    def __init__(self, path, fernet: Fernet, **kwargs):
        super().__init__(path, **kwargs)
        self.fernet = fernet

    def read(self):
        try:
            raw = self._handle.read()
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
        try:
            json_str = json.dumps(data, separators=(",", ":")).encode()
            token = self.fernet.encrypt(json_str)
            encoded = base64.urlsafe_b64encode(token).decode()
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(encoded)
            logger.info("💾 DB written and encrypted successfully")
        except Exception as e:
            logger.error(f"❌ Failed to write DB: {e}")
            raise

class SecureDB:
    """Handles encryption/decryption and PIN logic for DB."""
    def __init__(self):
        self.db = None
        self.fernet = None
        self._passphrase = None
        self._unlocked = False
        self._failed_attempts = 0

    def _load_salt(self):
        if os.path.exists(SALT_FILE):
            salt = open(SALT_FILE, "rb").read()
            logger.debug(f"🔑 Loaded existing KDF salt ({len(salt)} bytes)")
        else:
            salt = os.urandom(16)
            open(SALT_FILE, "wb").write(salt)
            logger.info(f"🔑 Generated new KDF salt and saved to disk")
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
            # Test read
            _ = self.db.all()
            logger.info("✅ Database unlocked successfully")
            self._passphrase = pin
            self._unlocked = True
            self._failed_attempts = 0
            return True
        except InvalidToken:
            self._failed_attempts += 1
            attempts_left = MAX_PIN_ATTEMPTS - self._failed_attempts
            logger.warning(
                f"❌ Unlock failed ({self._failed_attempts}/{MAX_PIN_ATTEMPTS}). "
                f"Attempts left: {attempts_left}"
            )
            if self._failed_attempts >= MAX_PIN_ATTEMPTS:
                logger.critical("☠️ Maximum PIN attempts exceeded. Wiping DB and salt!")
                self._wipe_db()
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error while unlocking DB: {e}")
            return False

    def lock(self):
        """Lock the DB for inactivity."""
        if self._unlocked and self.db:
            self.db.close()
            self._unlocked = False
            logger.info("🔒 Database locked")

    def is_unlocked(self) -> bool:
        return self._unlocked

    def _wipe_db(self):
        """Wipe the DB and salt for security."""
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            logger.warning("🗑️ DB file deleted")
        if os.path.exists(SALT_FILE):
            os.remove(SALT_FILE)
            logger.warning("🗑️ Salt file deleted")
        self._passphrase = None
        self._unlocked = False
        self._failed_attempts = 0
        logger.critical("💥 Database and salt wiped due to security policy")

    def has_pin(self) -> bool:
        """Returns True if DB appears to be encrypted (PIN-protected), False otherwise."""
        if not os.path.exists(DB_FILE) or not os.path.exists(SALT_FILE):
            return False
        try:
            with open(DB_FILE, "rb") as f:
                data = f.read()
            if not data:
                return False
            token = base64.urlsafe_b64decode(data)
            # DB is PIN protected if contents look like Fernet token (length check)
            return len(token) > 64
        except Exception:
            return False

secure_db = SecureDB()
