#!/usr/bin/env bash
set -e

# -----------------------------
# setup_secure_db.sh
# -----------------------------
# Generates a new 16-byte salt and replaces any existing KDF_SALT in secure_db.py
# WILL REFUSE to overwrite KDF_SALT if DB exists unless --force-reset is passed.

# 1) Navigate to this script's directory
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$dir"

# 2) Verify secure_db.py exists
if [[ ! -f secure_db.py ]]; then
  echo "ERROR: secure_db.py not found in $dir"
  exit 1
fi

# 3) Refuse to overwrite salt if DB exists unless forced
if [[ -f "data/db.json" ]] && [[ "$1" != "--force-reset" ]]; then
  echo "❌ DB exists. Refusing to overwrite KDF_SALT without --force-reset."
  exit 1
fi

# 4) Generate a new 16-byte salt (hex encoded)
SALT_HEX=$(python3 - << 'EOF'
import os
print(os.urandom(16).hex())
EOF
)

echo "Generated new salt: $SALT_HEX"

# 5) Remove any existing KDF_SALT lines
sed -i "/^KDF_SALT =/d" secure_db.py

# 6) Insert the new KDF_SALT right below the UNLOCK_TIMEOUT definition
sed -i "/^UNLOCK_TIMEOUT =/a KDF_SALT = bytes.fromhex(\"$SALT_HEX\")" secure_db.py

echo "✅ Updated secure_db.py with new KDF_SALT in safe format."
