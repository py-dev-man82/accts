#!/usr/bin/env bash
set -e

# 1) Install system packages
echo "Updating apt and installing system packages..."
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip build-essential

# 2) Create & activate virtualenv
echo "Creating Python virtualenv..."
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate

# 3) Upgrade pip and install Python dependencies
echo "Upgrading pip and installing Python libraries..."
pip install --upgrade pip
pip install \
  python-telegram-bot \
  tinydb \
  cryptography \
  pandas \
  xlsxwriter \
  reportlab

# 4) Deactivate venv
deactivate

echo "✅ All dependencies installed. To start your bot:"
echo "   cd $(pwd)"
echo "   source venv/bin/activate"
echo "   python3 bot.py"
