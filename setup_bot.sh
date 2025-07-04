#!/usr/bin/env bash
set -e

# 1. Update and install system packages
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git build-essential

# 2. Create project directory
PROJECT_DIR="$HOME/tgaccts"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# 3. Clone your repo (or pull latest)
if [ ! -d ".git" ]; then
  git clone https://github.com/py-dev-man82/Accts.git .
else
  git pull origin main
fi
# 3a. Interactive config.py update
CONFIG_FILE="config.py"
if [ -f "$CONFIG_FILE" ]; then
  echo "Configuring $CONFIG_FILE …"
  read -p "Enter your BOT_TOKEN: " BOT_TOKEN
  read -p "Enter your Telegram user ID (ADMIN_TELEGRAM_ID): " ADMIN_ID
  read -p "Enter your DB_PASSPHRASE: " DB_PASS

  sed -i "s|^BOT_TOKEN.*|BOT_TOKEN         = \"${BOT_TOKEN}\"|"         "$CONFIG_FILE"
  sed -i "s|^ADMIN_TELEGRAM_ID.*|ADMIN_TELEGRAM_ID = ${ADMIN_ID}|"     "$CONFIG_FILE"
  sed -i "s|^DB_PASSPHRASE.*|DB_PASSPHRASE     = \"${DB_PASS}\"|"       "$CONFIG_FILE"

  echo "✅ Updated $CONFIG_FILE"
else
  echo "⚠️  $CONFIG_FILE not found—skipping configuration"
fi



# 4. Prepare data directory
mkdir -p data
chmod 700 data

# 5. Run the secure DB setup script
if [ -x "$(which setup_secure_db.sh 2>/dev/null)" ] || [ -f "setupdb.sh" ]; then
  echo "Running secure DB setup..."
  chmod +x setupdb.sh
  ./setupdb.sh
else
  echo "Warning: setup_secure_db.sh not found or not executable. Skipping DB setup."
fi

# 6. Create and activate Python venv
python3 -m venv venv
source venv/bin/activate

# 7. Upgrade pip and install Python dependencies
pip install --upgrade pip
pip install \
    python-telegram-bot \
    tinydb \
    cryptography \
    pandas \
    xlsxwriter \
    reportlab

# 8. (Optional) Initialize POT starting balance
# Uncomment and adjust if needed:
# python3 - << 'EOF'
# from secure_db import secure_db
# from config import POT_START
# secure_db.insert('pot', {'date': datetime.utcnow().isoformat(), 'starting_balance': POT_START})
# EOF

# 9. Deactivate venv
deactivate

# 10. Create systemd service
SERVICE_FILE="/etc/systemd/system/telegram-bot.service"
sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Telegram Accounting Bot (tgaccts)
After=network.target

[Service]
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python $PROJECT_DIR/bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 11. Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot.service
sudo systemctl start telegram-bot.service

# 12. Final message
echo "✅ Deployment complete!"
echo " • Check status: sudo systemctl status telegram-bot"
echo " • View logs:    sudo journalctl -u telegram-bot -f"
