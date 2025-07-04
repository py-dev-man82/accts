#!/usr/bin/env bash
set -e

# 1) cd into the script's directory
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$dir"

# 2) Ensure secure_db.py exists
if [[ ! -f secure_db.py ]]; then
  echo "ERROR: secure_db.py not found in $dir"
  exit 1
fi

# 3) Generate a new 16-byte salt (ASCII-escaped repr)
SALT_REPR=$(python3 - << 'EOF'
import os
print(repr(os.urandom(16)))
EOF
)

echo "Generated new KDF_SALT: $SALT_REPR"

# 4) Escape characters for sed
ESCAPED_SALT=$(printf %s "$SALT_REPR" | sed -e 's/[\/&]/\\&/g')

# 5) Remove any old placeholder comment and existing KDF_SALT line
sed -i '/^#.*salt.*literal/,/^KDF_SALT =/d' secure_db.py

# 6) Insert new KDF_SALT at top of file (after any initial comments)
sed -i "1 a KDF_SALT = $ESCAPED_SALT" secure_db.py

echo "Updated secure_db.py with new salt."

# 7) Prepare data directory
mkdir -p data
chmod 700 data
touch data/db.json
chmod 600 data/db.json

echo "✅ Secure DB setup complete."