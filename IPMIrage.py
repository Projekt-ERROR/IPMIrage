import sys
import time
import csv
import os
import subprocess
import yaml

# Ensure the script runs inside a virtual environment
if not hasattr(sys, 'real_prefix') and not (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
    print("[*] Virtual environment not detected. Please run:")
    print("    source venv/bin/activate && python IPMIrage.py")
    sys.exit(1)

# Dependencies check
try:
    import requests
    import pandas
except ImportError:
    print("[*] Installing missing dependencies...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    print("[*] Dependencies installed. Restarting script...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

# Load configuration and CSV
CONFIG_FILE = "config.yaml"
CSV_FILE = "mac_to_ip.csv"

# Check for config file
if not os.path.exists(CONFIG_FILE):
    print("ERROR: Missing configuration file for DHCP pool (config.yaml)")
    exit(1)

# Check for CSV file
if not os.path.exists(CSV_FILE):
    print("ERROR: Missing CSV file: mac_to_ip.csv")
    print("ERROR: Please create a CSV file with MAC-to-IP mappings.")
    exit(1)

# Load YAML config

with open(CONFIG_FILE, "r") as file:
    config = yaml.safe_load(file)

# Extracting settings from config.yaml
INTERFACE = config["network"]["interface"]
DHCP_RANGE_START = config["network"]["dhcp_range_start"]
DHCP_RANGE_END = config["network"]["dhcp_range_end"]
SUBNET_MASK = config["network"]["subnet_mask"]
GATEWAY = config["network"]["gateway"]

DHCP_CONFIG_FILE = config["dhcp"]["config_file"]
LEASES_FILE = config["dhcp"]["leases_file"]

IPMI_USER = config["ipmi"]["username"]
IPMI_PASS = config["ipmi"]["password"]


def create_dhcp_pool():
    """Create a temp DHCP pool using dnsmasq"""
    if os.geteuid() != 0:
        print("ERROR: This script must be run as root to configure DHCP.")
        exit(1)

    print("[*] Setting up DHCP pool for IPMI discovery...")

    # Create dnsmasq configuration dynamically
    dhcp_config = f"""
interface={INTERFACE}
dhcp-range={DHCP_RANGE_START},{DHCP_RANGE_END},12h
log-dhcp
"""

    # Write configuration file
    with open(DHCP_CONFIG_FILE, "w") as file:
        file.write(dhcp_config)

    # Restart dnsmasq to apply changes
    subprocess.run(["sudo", "systemctl", "restart", "dnsmasq"], check=True)
    print("[*] DHCP pool is running. Waiting for devices to obtain IPs...")


def get_dhcp_ip(mac_addr):
    """Find the DHCP-Assigned IP for a given MAC"""
    try with open(LEASE_FILE, "r") as file:
        leases = file.readlines()

        for lease in leases:
            parts = lease.slip()
            if mac_addr.lower() == parts[1].lower():
                return parts[2] # Assigned IP
    except Exceptions as e:
        print(f"ERROR: Reading DHCP leases: {e}")

    return None

def set_static_ip(dhcp_ip, static_ip, netmask, gateway):
    """Use ipmitool to configure a static IP."""
    commands = [
        f"ipmitool -I lanplus -H {dhcp_ip} -U {IPMI_USER} -P {IPMI_PASS} lan set 1 ipsrc static",
        f"ipmitool -I lanplus -H {dhcp_ip} -U {IPMI_USER} -P {IPMI_PASS} lan set 1 ipaddr {static_ip}",
        f"ipmitool -I lanplus -H {dhcp_ip} -U {IPMI_USER} -P {IPMI_PASS} lan set 1 netmask {netmask}",
        f"ipmitool -I lanplus -H {dhcp_ip} -U {IPMI_USER} -P {IPMI_PASS} lan set 1 defgw ipaddr {gateway}"
    ]

    for cmd in commands:
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            print(f"[*]Successfully set {static_ip} for {dhcp_ip}")
        else:
            print(f"ERROR: Setting {static_ip}: {result.stderr.decode().strip()}")

def main():
    """Assigns static IPs based on MAC discovery."""
    # Step 1: Start the DHCP server
    create_dhcp_pool()
    time.sleep(10)  # Give time for DHCP to assign IPs

    with open(CSV_FILE, "r") as file:
        reader = csv.reader(file)
        next(reader)  # Skip header

        for mac, static_ip, netmask, gateway in reader:
            print(f"[-] Looking for IP assigned to MAC: {mac}...")

            dhcp_ip = None
            attempts = 5  # Retry for a bit if IP isn't found immediately

            while attempts > 0:
                dhcp_ip = get_dhcp_ip(mac)
                if dhcp_ip:
                    break
                time.sleep(5)  # Wait for DHCP to assign an IP
                attempts -= 1

            if dhcp_ip:
                print(f"[*] Found {dhcp_ip} for {mac}. Assigning static IP {static_ip}...")
                set_static_ip(dhcp_ip, static_ip, netmask, gateway)
            else:
                print(f"[X] No DHCP IP found for MAC {mac}. Skipping...")


if __name__ == "__main__":
    main()
