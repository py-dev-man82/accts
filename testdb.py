from secure_db import secure_db

# Unlock with your actual PIN
if not secure_db.unlock("your-pin"):
    print("Unlock failed! Wrong PIN or DB corrupted.")
    exit()

# Insert a test customer
secure_db.insert("customers", {"name": "Test User"})

# Immediately read all customers
print("Customers after insert:", secure_db.all("customers"))

# Lock and unlock again, and read again
secure_db.lock()
if not secure_db.unlock("your-pin"):
    print("Unlock failed after relock!")
    exit()
print("Customers after re-unlock:", secure_db.all("customers"))
