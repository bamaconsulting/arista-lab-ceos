#!/usr/bin/env bash

set -euo pipefail

SERVER1_CONTAINER="clab-dc1_fabric-server1"
SERVER2_CONTAINER="clab-dc1_fabric-server2"
COUNT="5"
SELECTED_VLAN=""

usage() {
	echo "Usage: $0 [--vlan VLAN_ID] [--count N]"
	echo "Example: $0 --vlan 11 --count 5"
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--vlan)
			SELECTED_VLAN="$2"
			shift 2
			;;
		--count)
			COUNT="$2"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "Unknown argument: $1"
			usage
			exit 1
			;;
	esac
done

if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || (( COUNT < 1 )); then
	echo "Invalid --count value: $COUNT (must be a positive integer)"
	exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
	echo "docker command is required"
	exit 1
fi

for container in "$SERVER1_CONTAINER" "$SERVER2_CONTAINER"; do
	if ! docker ps --format '{{.Names}}' | grep -qx "$container"; then
		echo "Container not running: $container"
		echo "Start lab first, for example: sudo containerlab deploy -t lab.clab.yml"
		exit 1
	fi
done

declare -A VLAN_TO_IP

while IFS= read -r line; do
	iface="$(awk '{print $2}' <<<"$line")"
	ip_cidr="$(awk '{print $4}' <<<"$line")"
	ip="${ip_cidr%%/*}"

	if [[ "$iface" =~ ^bond0\.([0-9]+)$ ]]; then
		vlan="${BASH_REMATCH[1]}"
		VLAN_TO_IP["$vlan"]="$ip"
	fi
done < <(docker exec "$SERVER2_CONTAINER" ip -o -4 addr show)

if [[ ${#VLAN_TO_IP[@]} -eq 0 ]]; then
	echo "No VLAN interfaces found on $SERVER2_CONTAINER (expected bond0.<VLAN>)."
	echo "Ensure server2 is configured (scripts/setup-server2.sh)."
	exit 1
fi

mapfile -t AVAILABLE_VLANS < <(printf '%s\n' "${!VLAN_TO_IP[@]}" | sort -n)

echo "Detected valid VLANs on $SERVER2_CONTAINER: ${#AVAILABLE_VLANS[@]}"
echo "Available VLAN IDs: ${AVAILABLE_VLANS[*]}"

if [[ -n "$SELECTED_VLAN" ]]; then
	if [[ -z "${VLAN_TO_IP[$SELECTED_VLAN]:-}" ]]; then
		echo "VLAN $SELECTED_VLAN is not available on $SERVER2_CONTAINER"
		exit 1
	fi
else
	while true; do
		read -r -p "Select VLAN ID for ping test: " SELECTED_VLAN
		if [[ -n "${VLAN_TO_IP[$SELECTED_VLAN]:-}" ]]; then
			break
		fi
		echo "Invalid VLAN ID. Choose one of: ${AVAILABLE_VLANS[*]}"
	done
fi

TARGET_IP="${VLAN_TO_IP[$SELECTED_VLAN]}"
SOURCE_INTERFACE="bond0.${SELECTED_VLAN}"

if ! docker exec "$SERVER1_CONTAINER" ip link show "$SOURCE_INTERFACE" >/dev/null 2>&1; then
	echo "Interface '$SOURCE_INTERFACE' not found in $SERVER1_CONTAINER"
	echo "Ensure server interfaces are configured (scripts/setup-server1.sh)."
	exit 1
fi

mapfile -t SERVER1_VLANS < <(
	docker exec "$SERVER1_CONTAINER" ip -o -4 addr show | awk '{print $2}' | sed -n 's/^bond0\.\([0-9]\+\)$/\1/p' | sort -n
)

if [[ ${#SERVER1_VLANS[@]} -eq 0 ]]; then
	echo "No VLAN interfaces found on $SERVER1_CONTAINER (expected bond0.<VLAN>)."
	echo "Ensure server1 is configured (scripts/setup-server1.sh)."
	exit 1
fi

echo "Bringing up all VLAN interfaces on $SERVER1_CONTAINER: ${SERVER1_VLANS[*]}"
for vlan in "${SERVER1_VLANS[@]}"; do
	docker exec "$SERVER1_CONTAINER" sh -lc "ip link set bond0.${vlan} up"
done

echo "Pinging $TARGET_IP from $SERVER1_CONTAINER via $SOURCE_INTERFACE (count=$COUNT)"
docker exec "$SERVER1_CONTAINER" ping -I "$SOURCE_INTERFACE" -c "$COUNT" "$TARGET_IP"
