#!/usr/bin/env bash
set -e

# 1. Update and install system packages
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git build-essential

# 2. Create project directory
PROJECT_DIR="\$HOME/telegram_accounting_bot"
mkdir -p "\$PROJECT_DIR"
cd "\$PROJECT_DIR"

# 3. Clone your repo (or pull latest)
if [ ! -d ".git" ]; then
  git clone https://github.com/py-dev-man82/Accts.git .
else
  git pull origin main
fi

# 4. Prepare data directory
mkdir -p data
chmod 700 data

# 5. Create and activate Python venv
python3 -m venv venv
source venv/bin/activate

# 6. Install Python dependencies
pip install --upgrade pip
pip install \
    python-telegram-bot \
    tinydb \
    cryptography \
    pandas \
    xlsxwriter

# 7. (Optional) Initialize POT if you have a starting balance
# python3 - << 'EOF'
# from secure_db import secure_db
# from config import POT_START
# secure_db.insert('pot', {'date': datetime.utcnow().isoformat(), 'starting_balance': POT_START})
# EOF

# 8. Deactivate venv
deactivate

# 9. Create systemd service
SERVICE_FILE="/etc/systemd/system/telegram-accounting-bot.service"
sudo tee "\$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Telegram Accounting Bot
After=network.target

[Service]
User=\$USER
WorkingDirectory=\$PROJECT_DIR
ExecStart=\$PROJECT_DIR/venv/bin/python \$PROJECT_DIR/bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 10. Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable telegram-accounting-bot.service
sudo systemctl start telegram-accounting-bot.service

echo "✅ Deployment complete!"
echo " • Check status: sudo systemctl status telegram-accounting-bot"
echo " • View logs:    sudo journalctl -u telegram-accounting-bot -f"
