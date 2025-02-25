#!/bin/bash

echo "[*] Setting up IPMIrage..."
echo "[*] Checking for Python3..."

if ! command -v python3 &>/dev/null; then
    echo "[-] Python3 is not installed. Please install"
    exit 1
fi

# Create virtual ENV

echo "[*] Creating virtual enviroment..."
python3 -m venv venv

# Activate the VENV
source venv/bin/activate

# Upgrade pip and install dependencies
echo "[*] Installing dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "[*] Setup complete"
echo "To run IPMIrage, actiavte the virtual environment first:"
echo "source venv/bin/active && python IPMIrage.py"
