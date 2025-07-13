from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.fernet import Fernet
import base64

with open("data/kdf_salt.bin", "rb") as f:
    salt = f.read()
pin = "1234"   # Use **exactly** the PIN you set
kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
key = kdf.derive(pin.encode("utf-8"))
token = base64.urlsafe_b64encode(key)
fernet = Fernet(token)

with open("data/db.json") as f:
    raw = f.read()
token = base64.urlsafe_b64decode(raw.encode())
decrypted = fernet.decrypt(token)
print(decrypted)
