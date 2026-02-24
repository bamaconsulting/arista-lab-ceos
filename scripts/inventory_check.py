#!/usr/bin/env python3

"""Simple eAPI inventory checker.

This script reads devices from an Ansible inventory group,
connects to each EOS device via eAPI, and prints:
- inventory hostname,
- device hostname,
- EOS software version.

Where device data comes from:
- `ansible-inventory -i <inventory> --list` output (JSON)
- group membership (for example `FABRIC`)
- `_meta.hostvars.<host>.ansible_host` as management IP/FQDN

How connection works:
- `pyeapi.client.connect(...)` creates a session to each device
- the script executes `show hostname` and `show version`
- values are read from eAPI JSON response and printed as a table
"""

import argparse
import json
import subprocess
from pathlib import Path

import pyeapi


def parse_args() -> argparse.Namespace:
	"""Define and parse CLI arguments."""
	parser = argparse.ArgumentParser(description="Check hostname and EOS version via eAPI")
	parser.add_argument("--inventory", default="inventory/inventory.yml", help="Path to Ansible inventory")
	parser.add_argument("--group", default="FABRIC", help="Inventory group name")
	parser.add_argument("--username", default="admin", help="eAPI username")
	parser.add_argument("--password", default="admin", help="eAPI password")
	parser.add_argument("--transport", choices=["http", "https"], default="https", help="eAPI transport")
	parser.add_argument("--port", type=int, default=443, help="eAPI port")
	return parser.parse_args()


def resolve_inventory_path(inventory_path: str) -> str:
	"""Resolve inventory path for both common run locations.

	- If the provided path exists as-is, use it.
	- Otherwise, try the same path relative to repo root (parent of scripts/).
	"""
	path = Path(inventory_path)
	if path.is_file():
		return str(path)

	script_dir = Path(__file__).resolve().parent
	repo_root = script_dir.parent
	candidate = repo_root / inventory_path
	if candidate.is_file():
		return str(candidate)

	return inventory_path


def load_hosts(inventory_path: str, group: str) -> list[tuple[str, str]]:
	"""Load hosts from a group (including nested child groups).

	Returns a sorted list of tuples: (inventory_hostname, ansible_host).

	Details:
	- Inventory is parsed by shelling out to `ansible-inventory`.
	- Hosts are collected recursively from the selected group and all children.
	- For each host, connection target is resolved from `hostvars[host].ansible_host`.
	  If `ansible_host` is missing, inventory hostname is used.
	"""
	# Query Ansible inventory and return full structure as JSON.
	cmd = ["ansible-inventory", "-i", inventory_path, "--list"]
	proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
	inv = json.loads(proc.stdout)

	if group not in inv:
		raise ValueError(f"Group '{group}' not found in inventory")

	# Track visited groups to avoid loops in recursive traversal.
	visited = set()

	def collect(group_name: str) -> set[str]:
		"""Recursively collect hosts from a group and its children."""
		if group_name in visited:
			return set()
		visited.add(group_name)

		data = inv.get(group_name, {})
		hosts = set(data.get("hosts", []))
		for child in data.get("children", []):
			hosts.update(collect(child))
		return hosts

	# hostvars carries per-host variables from inventory files (including ansible_host).
	hostvars = inv.get("_meta", {}).get("hostvars", {})
	result = []
	for host in sorted(collect(group)):
		# Resolve management endpoint used for eAPI connection.
		ip = hostvars.get(host, {}).get("ansible_host", host)
		result.append((host, ip))
	return result


def main() -> int:
	"""Program entrypoint.

	Flow:
	1) Parse arguments.
	2) Load hosts from inventory.
	3) Connect to each host via eAPI.
	4) Print hostname and EOS version table.
	"""
	args = parse_args()
	inventory_path = resolve_inventory_path(args.inventory)

	try:
		hosts = load_hosts(inventory_path, args.group)
	except Exception as exc:
		print(f"Inventory error: {exc}")
		return 2

	if not hosts:
		print("No hosts found.")
		return 2

	print(f"{'Inventory Host':<15} {'Hostname (device)':<20} {'EOS Version':<35}")
	print("-" * 75)

	for inventory_host, ip in hosts:
		try:
			# Create pyeapi node session to the target device.
			# transport=https + port=443 matches lab eAPI settings.
			# Credentials come from CLI args (default admin/admin).
			node = pyeapi.client.connect(
				transport=args.transport,
				host=ip,
				username=args.username,
				password=args.password,
				port=args.port,
				return_node=True,
				timeout=30,
			)
			# Read software version from EOS via eAPI command execution.
			version_response = node.enable(["show version"])[0]
			version_data = version_response.get("result", version_response)

			# Read configured device hostname from EOS via eAPI command execution.
			hostname_response = node.enable(["show hostname"])[0]
			hostname_data = hostname_response.get("result", hostname_response)

			hostname = hostname_data.get("hostname", "n/a")
			version = version_data.get("version", "n/a")
			print(f"{inventory_host:<15} {hostname:<20} {version:<35}")
		except Exception as exc:
			print(f"{inventory_host:<15} {'ERROR':<20} {str(exc):<35}")

	return 0


if __name__ == "__main__":
	raise SystemExit(main())

