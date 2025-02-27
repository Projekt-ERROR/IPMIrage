#!/bin/bash

IP="$1"
STATIC_IP="$2"
NETMASK="$3"
GATEWAY="$4"
USERNAME="ADMIN"
PASSWORD="admin"

if [ -z "$IP" ] || [ -z "$STATIC_IP" ] || [ -z "$NETMASK" ] || [ -z "$GATEWAY" ]; then
    echo "  Usage: $0 <current_ip> <static_ip> <netmask> <gateway>"
    exit 1
fi

echo "  [*] Configuring IPMI for IP: $IP (New IP: $STATIC_IP)"

# Set static IP configuration
timeout 10s ipmitool -I lanplus -H "$IP" -U "$USERNAME" -P "$PASSWORD" lan set 1 ipsrc static
timeout 10s ipmitool -I lanplus -H "$IP" -U "$USERNAME" -P "$PASSWORD" lan set 1 ipaddr "$STATIC_IP"

# Changing IP temp to gateway to connect to IPMI
echo "  [-] Changing user IP to default gateway temporarily"
sudo ip addr add "$GATEWAY"/24 dev eth0

# Wait for the IP change to apply
sleep 5

echo "  [*] Switching to new IP: $STATIC_IP"

# Set netmask and gateway using the new IP
timeout 10s ipmitool -I lanplus -H "$STATIC_IP" -U "$USERNAME" -P "$PASSWORD" lan set 1 netmask "$NETMASK"
timeout 10s ipmitool -I lanplus -H "$STATIC_IP" -U "$USERNAME" -P "$PASSWORD" lan set 1 defgw ipaddr "$GATEWAY"

# Reset BMC to apply settings
echo "  [-] Resetting BMC to apply settings..."
ipmitool -I lanplus -H "$STATIC_IP" -U "$USERNAME" -P "$PASSWORD" mc reset warm

# Restoring networking configurations
echo "  [*] Restoring network configurations"
sudo ip addr del "$GATEWAY"/24 dev eth0

echo "  [*] IPMI configuration completed for IP: $STATIC_IP"
