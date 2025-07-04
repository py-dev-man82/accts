#!/usr/bin/env bash set -e

1. Ensure we're in the repo root

ddir="$(dirname "$0")" && cd "$ddir"

2. Check secure_db.py exists

if [[ ! -f secure_db.py ]]; then echo "ERROR: secure_db.py not found in $(pwd)" exit 1 fi

3. Generate a new 16-byte KDF salt (ASCII-escaped representation)

SALT_BYTES=$(python3 - << 'EOF' import os print(repr(os.urandom(16))) EOF )

echo "Generated new KDF_SALT: $SALT_BYTES"

4. Replace existing KDF_SALT line in secure_db.py

Matches lines starting with KDF_SALT =

sed -i "s|^KDF_SALT =.*|KDF_SALT = $SALT_BYTES|" secure_db.py

echo "Updated secure_db.py with new salt."

5. Prepare data directory

mkdir -p data ochmod 700 data touch data/db.json chmod 600 data/db.json

echo "Created data/db.json (empty) with restrictive permissions."

echo "✅ Secure DB setup complete."

