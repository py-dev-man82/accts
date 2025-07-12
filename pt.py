import base64
import json
from tinydb import TinyDB
from cryptography.fernet import Fernet

# Generate a key for test (do NOT use in prod)
key = Fernet.generate_key()
fernet = Fernet(key)

class EncryptedJSONStorage(JSONStorage):
    def __init__(self, path, fernet: Fernet, **kwargs):
        super().__init__(path, **kwargs)
        self.fernet = fernet
    def read(self):
        raw = self._handle.read()
        if not raw:
            return {}
        token = base64.urlsafe_b64decode(raw.encode())
        decrypted = self.fernet.decrypt(token)
        return json.loads(decrypted.decode())
    def write(self, data):
        json_str = json.dumps(data, separators=(",", ":")).encode()
        token = self.fernet.encrypt(json_str)
        encoded = base64.urlsafe_b64encode(token).decode()
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(encoded)

db = TinyDB("data/test_enc.json", storage=lambda p: EncryptedJSONStorage(p, fernet))
db.insert({"foo": "bar"})
print("After insert:", db.all())
db.close()

# Try to re-open (same key)
db2 = TinyDB("data/test_enc.json", storage=lambda p: EncryptedJSONStorage(p, fernet))
print("Reloaded:", db2.all())
db2.close()
