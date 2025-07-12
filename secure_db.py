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
        except InvalidToken:
            logger.error("🔒 Decryption failed: wrong key or unencrypted DB")
            raise RuntimeError("Failed
