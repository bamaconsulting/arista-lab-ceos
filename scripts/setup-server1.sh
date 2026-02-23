#!/bin/bash

# --- 1. LACP Bonding Configuration ---
# Create the bond0 interface using IEEE 802.3ad (mode 4)
# miimon 100: checks link status every 100ms
# lacp_rate 1: requests LACP packets every 1 second (fast)
ip link add bond0 type bond mode 4 miimon 100 lacp_rate 1

# Bring physical interfaces down before adding them to the bond
ip link set eth1 down
ip link set eth2 down

# Set physical interfaces as slaves to bond0
ip link set eth1 master bond0
ip link set eth2 master bond0

# Bring the physical and bond interfaces up
ip link set eth1 up
ip link set eth2 up
ip link set bond0 up

# --- 2. VLAN Tagging (802.1Q) Configuration ---
# Iterate through required VLANs: 11, 12, 21, 22
# New addressing scheme: 10.10.VLAN.201
for vlan in 11 12 21 22; do
  echo "Configuring VLAN $vlan on server1 with IP 10.10.$vlan.201..."
  # Create a virtual sub-interface for the VLAN
  ip link add link bond0 name bond0.$vlan type vlan id $vlan
  # Assign the new IP address (10.10.VLAN.201)
  ip addr add 10.10.$vlan.201/24 dev bond0.$vlan
  # Bring the VLAN interface up
  ip link set bond0.$vlan up
done

echo "Server 1 configuration with new addressing complete!"