#!/usr/bin/env bash
set -e

# 1) Install system packages
echo "Installing system packages…"
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip build-essential git

# 2) Define and cd into PROJECT_DIR (~/accts)
PROJECT_DIR="$HOME/accts"
echo "Using project directory: $PROJECT_DIR"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# 3) Prepare data directory
echo "Preparing data directory…"
mkdir -p data
chmod 700 data

# 4) Run secure-DB init script if present
if [ -f setup_secure_db.sh ]; then
  echo "Running secure DB setup…"
  chmod +x setup_secure_db.sh
  ./setup_secure_db.sh
else
  echo "⚠️  setup_secure_db.sh not found—skipping DB init"
fi

# 5) Interactive config.py update (skip blank entries)
CONFIG_FILE="config.py"
if [ -f "$CONFIG_FILE" ]; then
  echo "Configuring $CONFIG_FILE…"

  read -p "Enter BOT_TOKEN (leave blank to keep existing): " BOT_TOKEN
  if [ -n "$BOT_TOKEN" ]; then
    sed -i "s|^BOT_TOKEN.*|BOT_TOKEN         = \"${BOT_TOKEN}\"|" "$CONFIG_FILE"
    echo "→ BOT_TOKEN updated"
  else
    echo "→ BOT_TOKEN unchanged"
  fi

  read -p "Enter ADMIN_TELEGRAM_ID (leave blank to keep existing): " ADMIN_ID
  if [ -n "$ADMIN_ID" ]; then
    sed -i "s|^ADMIN_TELEGRAM_ID.*|ADMIN_TELEGRAM_ID = ${ADMIN_ID}|" "$CONFIG_FILE"
    echo "→ ADMIN_TELEGRAM_ID updated"
  else
    echo "→ ADMIN_TELEGRAM_ID unchanged"
  fi

  read -p "Enter DB_PASSPHRASE (leave blank to keep existing): " DB_PASS
  if [ -n "$DB_PASS" ]; then
    sed -i "s|^DB_PASSPHRASE.*|DB_PASSPHRASE     = \"${DB_PASS}\"|" "$CONFIG_FILE"
    echo "→ DB_PASSPHRASE updated"
  else
    echo "→ DB_PASSPHRASE unchanged"
  fi
else
  echo "⚠️  $CONFIG_FILE not found—skipping configuration"
fi

# 6) Create & activate Python virtualenv
echo "Creating Python virtualenv…"
python3 -m venv venv
source venv/bin/activate

# 7) Install Python dependencies
echo "Installing Python dependencies…"
pip install --upgrade pip
pip install \
    python-telegram-bot \
    tinydb \
    cryptography \
    pandas \
    xlsxwriter \
    reportlab

# 8) Interactive POT starting balance
read -p "Enter initial POT starting balance (leave blank to skip): " POT_START
if [ -n "$POT_START" ]; then
  echo "Seeding POT with \$${POT_START}…"
  python3 - <<EOF
from secure_db import secure_db
from datetime import datetime
secure_db.insert('pot', {
    'date': datetime.utcnow().isoformat(),
    'starting_balance': ${POT_START}
})
EOF
  echo "→ POT seeded: \$${POT_START}"
else
  echo "→ Skipping POT initialization"
fi

# 9) Deactivate venv
deactivate

# 10) Create systemd service
echo "Creating systemd service…"
SERVICE_FILE="/etc/systemd/system/telegram-bot.service"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Telegram Accounting Bot (accts)
After=network.target

[Service]
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VPN ? $PROJECT_DIR/venv/bin/python $PROJECT_DIR/bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 11) Enable & start service
echo "Enabling and starting the service…"
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot
sudo systemctl restart telegram-bot

echo "✅ Setup complete!"
echo " • Service status:  sudo systemctl status telegram-bot"
echo " • Service logs:    sudo journalctl -u telegram-bot -f"