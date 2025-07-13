#!/usr/bin/env bash
set -e

# -----------------------------
# setup_secure_db.sh
# -----------------------------
# Generates a new 16-byte salt and writes it to data/kdf_salt.bin
# WILL REFUSE to overwrite the salt if DB exists unless --force-reset is passed.

# 1) Navigate to this script's directory
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$dir"

# 2) Ensure data directory exists
if [[ ! -d "data" ]]; then
  mkdir -p data
fi

# 3) Refuse to overwrite salt if DB exists unless forced
if [[ -f "data/db.json" ]] && [[ "$1" != "--force-reset" ]]; then
  echo "❌ DB exists. Refusing to overwrite kdf_salt.bin without --force-reset."
  exit 1
fi

# 4) Generate a new 16-byte salt (as raw bytes) and write to kdf_salt.bin
python3 - << 'EOF'
import os
with open("data/kdf_salt.bin", "wb") as f:
    f.write(os.urandom(16))
EOF

# 5) Lock the salt file read-only for all users
chmod 444 data/kdf_salt.bin

echo "✅ Wrote new 16-byte data/kdf_salt.bin and locked to read-only"

# 6) Print hex and md5sum for verification
echo
echo "----- SALT FILE HEXDUMP -----"
hexdump -C data/kdf_salt.bin

echo
echo "----- MD5SUMS -----"
md5sum data/kdf_salt.bin 2>/dev/null || echo "No salt file"
md5sum data/db.json 2>/dev/null || echo "No DB file"

echo "-----------------------------"
