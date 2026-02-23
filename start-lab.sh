#!/bin/bash

# --- Configuration ---
LAB_FILE="lab.clab.yml"
# Extracting management IPs directly from the YAML file to be dynamic
IPS=$(grep -oE '172\.100\.100\.[0-9]{1,3}' $LAB_FILE | sort -u)

echo "--- Step 1: Cleaning old SSH keys from known_hosts ---"
# Loop through each IP found in the lab file
for ip in $IPS; do
    echo "Removing $ip from ~/.ssh/known_hosts..."
    # -R removes the host key from the known_hosts file
    ssh-keygen -f "$HOME/.ssh/known_hosts" -R "$ip" &>/dev/null
done

echo ""
echo "--- Step 2: Deploying the fabric with reconfigure ---"
# --reconfigure: wipes old container configs and applies new ones
# --max-workers 2: limits concurrent startup to 2 nodes to prevent CPU spikes/freezing
sudo containerlab deploy -t $LAB_FILE --reconfigure --max-workers 2

echo ""
echo "--- Deployment finished ---"