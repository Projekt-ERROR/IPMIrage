#!/bin/bash
set -e

IP="$1"
STATIC_IP="$2"
NETMASK="$3"
GATEWAY="$4"

# Use environment variables if provided, otherwise use defaults
USERNAME="${USERNAME:-ADMIN}"
PASSWORD="${PASSWORD:-admin}"

# Function for error handling
handle_error() {
    echo "  [X] Error: $1"
    # Clean up temporary network config if we've changed it
    if [ ! -z "$TEMP_IP_ADDED" ]; then
        echo "  [*] Restoring network configurations"
        sudo ip addr del "$GATEWAY"/24 dev eth0 2>/dev/null || true
    fi
    exit 1
}

if [ -z "$IP" ] || [ -z "$STATIC_IP" ] || [ -z "$NETMASK" ] || [ -z "$GATEWAY" ]; then
    echo "  Usage: $0 <current_ip> <static_ip> <netmask> <gateway>"
    exit 1
fi

echo "  [*] Configuring IPMI for IP: $IP (New IP: $STATIC_IP)"

# Function to run ipmitool with timeout and error handling
run_ipmi_command() {
    local desc="$1"
    shift
    echo "  [-] $desc"
    
    # Try the command with a timeout
    if ! timeout 15s ipmitool -I lanplus -H "$@" -U "$USERNAME" -P "$PASSWORD" "${@:5}" 2>/dev/null; then
        echo "  [X] Failed: $desc"
        return 1
    fi
    return 0
}

# Set static IP configuration
if ! run_ipmi_command "Setting IP source to static" "$IP" lan set 1 ipsrc static; then
    handle_error "Failed to set IP source to static"
fi

if ! run_ipmi_command "Setting IP address" "$IP" lan set 1 ipaddr "$STATIC_IP"; then
    handle_error "Failed to set IP address"
fi

# Add temporary IP for gateway to connect to IPMI
echo "  [-] Changing user IP to default gateway temporarily"
sudo ip addr add "$GATEWAY"/24 dev eth0 && TEMP_IP_ADDED=1 || handle_error "Failed to add temporary IP"

# Wait for the IP change to apply
echo "  [-] Waiting for IP change to apply..."
sleep 5

echo "  [*] Switching to new IP: $STATIC_IP"

# Set netmask and gateway using the new IP
if ! run_ipmi_command "Setting network mask" "$STATIC_IP" lan set 1 netmask "$NETMASK"; then
    handle_error "Failed to set network mask"
fi

if ! run_ipmi_command "Setting default gateway" "$STATIC_IP" lan set 1 defgw ipaddr "$GATEWAY"; then
    handle_error "Failed to set default gateway"
fi

# Reset BMC to apply settings
echo "  [-] Resetting BMC to apply settings..."
if ! ipmitool -I lanplus -H "$STATIC_IP" -U "$USERNAME" -P "$PASSWORD" mc reset warm; then
    echo "  [!] BMC reset failed but configuration might still be applied"
fi

# Restoring networking configurations
echo "  [*] Restoring network configurations"
sudo ip addr del "$GATEWAY"/24 dev eth0 && TEMP_IP_ADDED=""

echo "  [*] IPMI configuration completed for IP: $STATIC_IP"
exit 0
