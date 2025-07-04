#!/usr/bin/env bash
set -e

# 1. Ensure we're in the repo root
cd "$(dirname "$0")"

# 2. Check secure_db.py exists
if [[ ! -f secure_db.py ]]; then
  echo "ERROR: secure_db.py not found in $(pwd)"
  exit 1
fi

# 3. Generate a new 16-byte KDF salt
SALT_BYTES=$(python3 - << 'EOF'
import os, reprlib
# use repr to get the Python literal form
print(repr(os.urandom(16)))
EOF
)

echo "Generated new KDF_SALT: $SALT_BYTES"

# 4. Replace existing KDF_SALT line in secure_db.py
#    Assumes line begins with KDF_SALT = 
sed -i \
  "/^KDF_SALT =/c\KDF_SALT = $SALT_BYTES" \
  secure_db.py

echo "Updated secure_db.py with new salt."

# 5. Prepare data directory
mkdir -p data
chmod 700 data
touch data/db.json
chmod 600 data/db.json

echo "Created data/db.json (empty) with restrictive permissions."

echo "✅ Secure DB setup complete."
