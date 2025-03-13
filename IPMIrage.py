import sys
import time
import csv
import os
import subprocess
import ipaddress

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML module not found.")
    print("Please ensure you've activated the virtual environment and PyYAML is installed:")
    print("    source venv/bin/activate && pip install pyyaml")
    sys.exit(1)
import re
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('ipmirage.log')
    ]
)
logger = logging.getLogger('IPMIrage')

# Ensure the script runs inside a virtual environment
def is_virtual_env():
    """Returns True if the script is running inside a virtual environment."""
    return (
            hasattr(sys, 'real_prefix') or
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix) or
            os.environ.get('VIRTUAL_ENV') is not None
            )

def format_mac_address(mac_address):
    """
    Validates and converts a MAC address to the standard hex format (XX:XX:XX:XX:XX:XX).
    
    Args:
        mac_address (str): MAC address in various formats (colons, dashes, dots, or without separators)
    
    Returns:
        str: Formatted MAC address or None if invalid
    """
    # Remove all separators and whitespace
    mac = mac_address.replace(':', '').replace('-', '').replace('.', '').replace(' ', '').upper()
    
    # Check if the result is a valid 12-character hex string
    if len(mac) != 12:
        return None
    
    try:
        # Verify all characters are valid hex
        int(mac, 16)
        
        # Format with colons
        formatted_mac = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
        return formatted_mac
    except ValueError:
        # Not a valid hex string
        return None

def validate_ip_address(ip_address):
    """Validates if the given string is a valid IP address."""
    try:
        ipaddress.ip_address(ip_address)
        return True
    except ValueError:
        return False

def setup_eth0_for_dhcp(interface, dhcp_ip):
    """Sets the specified interface to a static IP in the DHCP subnet before starting dnsmasq."""
    logger.info(f"Setting {interface} IP to {dhcp_ip} to serve DHCP requests...")

    try:
        # Flush any existing IP
        subprocess.run(f"sudo ip addr flush dev {interface}", shell=True, check=False)

        # Assign static IP in the same subnet as the DHCP pool
        subprocess.run(f"sudo ip addr add {dhcp_ip}/24 dev {interface}", shell=True, check=True)

        # Bring the interface up
        subprocess.run(f"sudo ip link set {interface} up", shell=True, check=True)

        logger.info(f"{interface} is now set to {dhcp_ip} and ready to assign IPs.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to configure interface {interface}: {e}")
        sys.exit(1)

def create_dhcp_pool(interface, dhcp_range_start, dhcp_range_end, subnet_mask, config_file):
    """Create a temporary DHCP pool using dnsmasq"""
    if os.geteuid() != 0:
        logger.error("This script must be run as root to configure DHCP.")
        sys.exit(1)

    logger.info("Setting up DHCP pool for IPMI discovery...")

    # Create dnsmasq configuration dynamically
    dhcp_config = f"""
interface={interface}
dhcp-range={dhcp_range_start},{dhcp_range_end},{subnet_mask},12h
log-dhcp
"""
    # Create directory for config file if it doesn't exist
    config_dir = os.path.dirname(config_file)
    if not os.path.exists(config_dir):
        try:
            os.makedirs(config_dir)
        except OSError as e:
            logger.error(f"Failed to create directory {config_dir}: {e}")
            sys.exit(1)

    # Write configuration file
    try:
        with open(config_file, "w") as file:
            file.write(dhcp_config)
    except IOError as e:
        logger.error(f"Failed to write DHCP configuration file: {e}")
        sys.exit(1)

    # Check if dnsmasq is installed
    try:
        subprocess.run(["which", "dnsmasq"], check=True, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError:
        logger.error("dnsmasq is not installed. Please install it with: sudo apt-get install dnsmasq")
        sys.exit(1)

    # Restart dnsmasq to apply changes
    try:
        subprocess.run(["sudo", "systemctl", "restart", "dnsmasq"], check=True)
        logger.info("DHCP pool is running. Waiting for devices to obtain IPs...")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to start dnsmasq: {e}")
        sys.exit(1)

def get_dhcp_ip(mac_addr, leases_file):
    """Find the DHCP-Assigned IP for a given MAC"""
    try:
        if not os.path.exists(leases_file):
            logger.warning(f"DHCP leases file not found: {leases_file}")
            return None
            
        with open(leases_file, "r") as file:
            leases = file.readlines()

        for lease in leases:
            parts = lease.split()
            if len(parts) >= 3 and mac_addr.lower() == parts[1].lower():
                return parts[2]  # Assigned IP
                
        logger.debug(f"No lease found for MAC: {mac_addr}")
    except Exception as e:
        logger.error(f"Error reading DHCP leases: {e}")

    return None

def configure_ipmi_bash(dhcp_ip, static_ip, netmask, gateway, username, password, script_path="./ipmi_set_ip.sh"):
    """Calls an external Bash script to configure IPMI."""
    if not os.path.exists(script_path):
        logger.error(f"IPMI configuration script not found: {script_path}")
        return False
        
    try:
        # Make sure the script is executable
        os.chmod(script_path, 0o755)
        
        # Pass the IPMI credentials to the script via environment variables
        env = os.environ.copy()
        env["USERNAME"] = username
        env["PASSWORD"] = password
        
        result = subprocess.run(
            [script_path, dhcp_ip, static_ip, netmask, gateway],
            env=env,
            check=True,
            capture_output=True,
            text=True
        )
        
        logger.info(f"Successfully configured IPMI: {static_ip}")
        logger.debug(f"IPMI configuration output: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to configure IPMI for {static_ip}: {e}")
        logger.debug(f"Error output: {e.stderr}")
        return False

def parse_csv_file(csv_file):
    """Parse the MAC-to-IP CSV file with validation."""
    valid_entries = []
    
    try:
        with open(csv_file, "r") as file:
            reader = csv.reader(file)
            header = next(reader)  # Skip header
            
            # Check if header has the expected columns
            if len(header) < 4:
                logger.error(f"CSV file must have at least 4 columns: MAC, STATIC_IP, NETMASK, GATEWAY. Found: {header}")
                sys.exit(1)
            
            line_num = 1
            for row in reader:
                line_num += 1
                
                if len(row) < 4:
                    logger.warning(f"Line {line_num}: Incomplete data: {row}")
                    continue
                
                mac, static_ip, netmask, gateway = row[:4]
                
                # Validate and format MAC address
                formatted_mac = format_mac_address(mac)
                if not formatted_mac:
                    logger.warning(f"Line {line_num}: Invalid MAC address format: {mac}")
                    continue
                
                # Validate IP addresses
                if not all(validate_ip_address(ip) for ip in [static_ip, gateway]):
                    logger.warning(f"Line {line_num}: Invalid IP address in: {row}")
                    continue
                
                # Validate netmask
                try:
                    ipaddress.IPv4Network(f"0.0.0.0/{netmask}")
                except ValueError:
                    logger.warning(f"Line {line_num}: Invalid netmask: {netmask}")
                    continue
                
                valid_entries.append((formatted_mac, static_ip, netmask, gateway))
                
        logger.info(f"Successfully loaded {len(valid_entries)} valid entries from CSV file")
        return valid_entries
    except Exception as e:
        logger.error(f"Error parsing CSV file {csv_file}: {e}")
        sys.exit(1)

def setup_environment():
    """Check environment and load configuration."""
    if not is_virtual_env():
        print("[*] Virtual environment not detected. Please run:")
        print("    source venv/bin/activate && sudo venv/bin/python IPMIrage.py")
        sys.exit(1)
        
    if os.geteuid() != 0:
        print("ERROR: This script must be run as root to configure DHCP and networking.")
        print("Please run with: sudo venv/bin/python IPMIrage.py")
        sys.exit(1)
        
    script_dir = Path(__file__).parent.absolute()
    config_file = script_dir / "config.yaml"
    csv_file = script_dir / "mac_to_ip.csv"

    # Check for config file
    if not config_file.exists():
        print("ERROR: Missing configuration file for DHCP pool (config.yaml)")
        sys.exit(1)

    # Check for CSV file
    if not csv_file.exists():
        print("ERROR: Missing CSV file: mac_to_ip.csv")
        print("ERROR: Please create a CSV file with MAC-to-IP mappings.")
        sys.exit(1)
        
    # Check for ipmitool
    try:
        subprocess.run(["which", "ipmitool"], check=True, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError:
        print("ERROR: ipmitool is not installed. Please install it with: sudo apt-get install ipmitool")
        sys.exit(1)
        
    # Load YAML config
    try:
        with open(config_file, "r") as file:
            config = yaml.safe_load(file)
        return config, str(csv_file)
    except Exception as e:
        print(f"ERROR: Failed to load configuration: {e}")
        sys.exit(1)

def main():
    """Assigns static IPs based on MAC discovery."""
    # Setup environment and load configuration
    config, csv_file = setup_environment()

    # Extracting settings from config.yaml
    interface = config["network"]["interface"]
    dhcp_range_start = config["network"]["dhcp_range_start"]
    dhcp_range_end = config["network"]["dhcp_range_end"]
    subnet_mask = config["network"]["subnet_mask"]
    gateway = config["network"]["gateway"]

    dhcp_config_file = config["dhcp"]["config_file"]
    leases_file = config["dhcp"]["leases_file"]

    ipmi_user = config["ipmi"]["username"]
    ipmi_pass = config["ipmi"]["password"]
    
    # Parse CSV file with validation
    valid_entries = parse_csv_file(csv_file)
    
    if not valid_entries:
        logger.error("No valid entries found in the CSV file. Exiting.")
        sys.exit(1)
    
    # Setup network interface for DHCP
    setup_eth0_for_dhcp(interface, gateway)

    # Start the DHCP server
    create_dhcp_pool(interface, dhcp_range_start, dhcp_range_end, subnet_mask, dhcp_config_file)
    
    # Wait for DHCP to start up
    logger.info("Waiting for DHCP server to initialize...")
    time.sleep(10)  # Allow DHCP time to start

    # Process each valid entry from the CSV file
    success_count = 0
    for mac, static_ip, netmask, gateway in valid_entries:
        logger.info(f"Looking for IP assigned to MAC: {mac}...")

        dhcp_ip = None
        attempts = 5  # Retry if IP isn't found immediately

        while attempts > 0:
            dhcp_ip = get_dhcp_ip(mac, leases_file)
            if dhcp_ip:
                break
            logger.info(f"Waiting for DHCP lease for MAC {mac}... ({attempts} attempts left)")
            time.sleep(5)
            attempts -= 1

        if dhcp_ip:
            logger.info(f"Found {dhcp_ip} for {mac}. Assigning static IP {static_ip}...")
            if configure_ipmi_bash(dhcp_ip, static_ip, netmask, gateway, ipmi_user, ipmi_pass):
                success_count += 1
        else:
            logger.warning(f"No DHCP IP found for MAC {mac} after multiple attempts. Skipping...")
    
    logger.info(f"IPMI configuration completed. Successfully configured {success_count}/{len(valid_entries)} devices.")

if __name__ == "__main__":
    main()
