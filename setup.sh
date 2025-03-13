#!/bin/bash
set -e

echo "[*] Setting up IPMIrage..."

# Check for root privileges for package installation
if [ "$EUID" -ne 0 ]; then
  echo "[!] Please run as root to install required packages"
  echo "    sudo ./setup.sh"
  exit 1
fi

# Detect package manager
if command -v apt-get &>/dev/null; then
  PKG_MANAGER="apt-get"
elif command -v yum &>/dev/null; then
  PKG_MANAGER="yum"
elif command -v dnf &>/dev/null; then
  PKG_MANAGER="dnf"
else
  echo "[!] Unsupported package manager. Please install the following packages manually:"
  echo "    - python3"
  echo "    - python3-venv"
  echo "    - ipmitool"
  echo "    - dnsmasq"
  exit 1
fi

echo "[*] Installing required system packages..."
if [ "$PKG_MANAGER" = "apt-get" ]; then
  apt-get update
  apt-get install -y python3 python3-venv ipmitool dnsmasq
elif [ "$PKG_MANAGER" = "yum" ] || [ "$PKG_MANAGER" = "dnf" ]; then
  $PKG_MANAGER install -y python3 python3-pip ipmitool dnsmasq
fi

echo "[*] Checking for Python3..."
if ! command -v python3 &>/dev/null; then
    echo "[-] Python3 is not installed. Installation failed."
    exit 1
fi

# Create virtual ENV
echo "[*] Creating virtual environment..."
python3 -m venv venv

# Check if virtual environment was created successfully
if [ ! -d "venv" ]; then
    echo "[-] Failed to create virtual environment."
    exit 1
fi

# Activate the VENV
source venv/bin/activate

# Upgrade pip and install dependencies
echo "[*] Installing Python dependencies"
pip install --upgrade pip
pip install -r requirements.txt

# Verify PyYAML is installed correctly
echo "[*] Verifying PyYAML installation"
if ! pip show PyYAML &>/dev/null; then
    echo "[!] PyYAML not found. Installing it directly..."
    pip install PyYAML>=6.0
fi

# Set correct permissions for scripts
echo "[*] Setting executable permissions on scripts"
chmod +x ipmi_set_ip.sh
chmod +x IPMIrage.py

# Create directories for dnsmasq if they don't exist
echo "[*] Setting up directories for dnsmasq"
mkdir -p /etc/dnsmasq.d
mkdir -p /var/lib/misc

echo "[*] Setup complete!"
echo "To run IPMIrage, activate the virtual environment first:"
echo "source venv/bin/activate && sudo venv/bin/python IPMIrage.py"
