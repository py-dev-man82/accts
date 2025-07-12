from secure_db import secure_db

PIN = "1122"

if not secure_db.unlock(PIN):
    print("Unlock failed! Wrong PIN or DB corrupted.")
    exit()

print("Before insert:", secure_db.all("customers"))
secure_db.insert("customers", {"name": "Test User"})
print("After insert:", secure_db.all("customers"))

secure_db.lock()  # ONLY call when finished with all DB ops
