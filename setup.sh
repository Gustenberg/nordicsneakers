#!/bin/bash
# Nordic Sneakers Monitor - Ubuntu Server Setup Script
# Run with: sudo bash setup.sh

set -e

echo "=========================================="
echo "  Nordic Sneakers Monitor - Setup Script"
echo "=========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo bash setup.sh)"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}
APP_DIR=$(pwd)

echo ""
echo "[1/6] Updating system packages..."
apt-get update
apt-get upgrade -y

echo ""
echo "[2/6] Installing Node.js 20.x..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

echo ""
echo "[3/6] Installing Python 3 and pip..."
apt-get install -y python3 python3-pip python3-venv

echo ""
echo "[4/6] Installing Playwright dependencies..."
apt-get install -y libnss3 libnspr4 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2

# Handle packages with t64 variants (Ubuntu 24.04+)
apt-get install -y libasound2t64 2>/dev/null || apt-get install -y libasound2
apt-get install -y libatk1.0-0t64 2>/dev/null || apt-get install -y libatk1.0-0
apt-get install -y libatk-bridge2.0-0t64 2>/dev/null || apt-get install -y libatk-bridge2.0-0
apt-get install -y libcups2t64 2>/dev/null || apt-get install -y libcups2
apt-get install -y libatspi2.0-0t64 2>/dev/null || apt-get install -y libatspi2.0-0

echo ""
echo "[5/6] Setting up application..."

# Install Node.js dependencies
sudo -u $ACTUAL_USER npm install

# Install Playwright browsers
sudo -u $ACTUAL_USER npx playwright install chromium

# Create Python virtual environment
sudo -u $ACTUAL_USER python3 -m venv venv
sudo -u $ACTUAL_USER ./venv/bin/pip install --upgrade pip
sudo -u $ACTUAL_USER ./venv/bin/pip install -r requirements.txt

# Create data and logs directories
mkdir -p data logs
chown $ACTUAL_USER:$ACTUAL_USER data logs

# Check for .env file
if [ ! -f .env ]; then
    echo ""
    echo "WARNING: .env file not found!"
    echo "Copy .env.example to .env and add your Nordic Sneakers cookie"
    cp .env.example .env
    chown $ACTUAL_USER:$ACTUAL_USER .env
fi

echo ""
echo "[6/6] Setting up systemd service..."

# Create systemd service
cat > /etc/systemd/system/nordic-sneakers.service << EOF
[Unit]
Description=Nordic Sneakers Monitor
After=network.target

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin:/usr/bin"
Environment="HEADLESS=true"
Environment="APP_ENV=production"
ExecStart=$APP_DIR/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload
systemctl enable nordic-sneakers

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "IMPORTANT: Edit .env file with your Nordic Sneakers cookie:"
echo "  nano .env"
echo ""
echo "Commands:"
echo "  Start:   sudo systemctl start nordic-sneakers"
echo "  Stop:    sudo systemctl stop nordic-sneakers"
echo "  Status:  sudo systemctl status nordic-sneakers"
echo "  Logs:    sudo journalctl -u nordic-sneakers -f"
echo ""
echo "Dashboard will be available at: http://YOUR_IP:8000"
echo ""
echo "To start now, run: sudo systemctl start nordic-sneakers"
