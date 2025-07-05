#!/usr/bin/env bash
set -e

# -----------------------------
# setup_secure_db.sh
# -----------------------------
# Generates a new 16-byte salt and replaces any existing KDF_SALT in secure_db.py

# 1) Navigate to this script's directory
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$dir"

# 2) Verify secure_db.py exists
if [[ ! -f secure_db.py ]]; then
  echo "ERROR: secure_db.py not found in $dir"
  exit 1
fi

# 3) Generate a new 16-byte salt (Python repr)
SALT_REPR=$(python3 - << 'EOF'
import os
print(repr(os.urandom(16)))
EOF
)

echo "Generated new salt: $SALT_REPR"

# 4) Remove any existing KDF_SALT lines
sed -i "/^KDF_SALT =/d" secure_db.py

# 5) Insert the new KDF_SALT right below the UNLOCK_TIMEOUT definition
sed -i "/^UNLOCK_TIMEOUT =/a KDF_SALT = $SALT_REPR" secure_db.py

echo "Updated secure_db.py with new KDF_SALT. Editing complete."
