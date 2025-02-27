import sys
import time
import csv
import os
import subprocess
import yaml
import ipaddress

# Ensure the script runs inside a virtual environment
def is_virtual_env():
    """Returns True if the script is running inside a virtual environment."""
    return (
            hasattr(sys, 'real_prefix') or
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix) or
            os.environ.get('VIRTUAL_ENV') is not None
            )

if not is_virtual_env():
    print("[*] Virtual environment not detected. Please run:")
    print("    source venv/bin/activate && sudo venv/bin/python IPMIrage.py")
    sys.exit(1)

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

def setup_eth0_for_dhcp(interface, dhcp_ip):
    """Sets eth0 to a static IP in the DHCP subnet before starting dnsmasq."""
    print(f"[*] Setting {interface} IP to {dhcp_ip} to serve DHCP requests...")

    # Flush any existing IP
    subprocess.run(f"sudo ip addr flush dev {interface}", shell=True, check=False)

    # Assign static IP in the same subnet as the DHCP pool
    subprocess.run(f"sudo ip addr add {dhcp_ip}/24 dev {interface}", shell=True, check=True)

    # Bring the interface up
    subprocess.run(f"sudo ip link set {interface} up", shell=True, check=True)

    print(f"[*] {interface} is now set to {dhcp_ip} and ready to assign IPs.")

def create_dhcp_pool():
    """Create a temp DHCP pool using dnsmasq"""
    if os.geteuid() != 0:
        print("ERROR: This script must be run as root to configure DHCP.")
        exit(1)

    print("[*] Setting up DHCP pool for IPMI discovery...")

    # Create dnsmasq configuration dynamically
    dhcp_config = f"""
interface={INTERFACE}
dhcp-range={DHCP_RANGE_START},{DHCP_RANGE_END},{SUBNET_MASK},12h
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
    try:
        with open(LEASES_FILE, "r") as file:
            leases = file.readlines()

        for lease in leases:
            parts = lease.split()
            if mac_addr.lower() == parts[1].lower():
                return parts[2]  # Assigned IP
    except Exception as e:
        print(f"ERROR: Reading DHCP leases: {e}")

    return None

def configure_ipmi_bash(dhcp_ip, static_ip, netmask, gateway):
    """Calls an external Bash script to configure IPMI."""
    try:
        subprocess.run(["./ipmi_set_ip.sh", dhcp_ip, static_ip, netmask, gateway], check=True)
        print(f"    [*] Successfully configured IPMI: {static_ip}")
    except subprocess.CalledProcessError:
        print(f"    ERROR: Failed to configure IPMI for {static_ip}")

def main():
    """Assigns static IPs based on MAC discovery."""
    setup_eth0_for_dhcp(INTERFACE, "192.168.100.1")

    # Start the DHCP server
    create_dhcp_pool()
    time.sleep(10)  # Allow DHCP time to assign IPs

    with open(CSV_FILE, "r") as file:
        reader = csv.reader(file)
        next(reader)  # Skip header

        for mac, static_ip, netmask, gateway in reader:
            print(f"[-] Looking for IP assigned to MAC: {mac}...")

            dhcp_ip = None
            attempts = 5  # Retry if IP isn't found immediately

            while attempts > 0:
                dhcp_ip = get_dhcp_ip(mac)
                if dhcp_ip:
                    break
                time.sleep(5)
                attempts -= 1

            if dhcp_ip:
                print(f"[*] Found {dhcp_ip} for {mac}. Assigning static IP {static_ip}...")
                configure_ipmi_bash(dhcp_ip, static_ip, netmask, gateway)
            else:
                print(f"[X] No DHCP IP found for MAC {mac}. Skipping...")

if __name__ == "__main__":
    main()

