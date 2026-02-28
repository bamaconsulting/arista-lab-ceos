#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pyeapi


YELLOW = "\033[33m"
GREEN = "\033[32m"
RESET = "\033[0m"

MAC_ENTRY_RE = re.compile(r"^\s*\d+\s+[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\s+(STATIC|DYNAMIC)\s+\S+", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Run 'show mac address-table vlan <VLAN>' on selected devices via eAPI")
	parser.add_argument("--inventory", default="inventory/inventory.yml", help="Path to Ansible inventory")
	parser.add_argument("--group", default="DC1_L3_LEAVES", help="Inventory group with devices")
	parser.add_argument("--username", default="admin", help="eAPI username")
	parser.add_argument("--password", default="admin", help="eAPI password")
	parser.add_argument("--transport", choices=["http", "https"], default="https", help="eAPI transport")
	parser.add_argument("--port", type=int, default=443, help="eAPI port")
	parser.add_argument("--timeout", type=int, default=30, help="eAPI connection timeout in seconds")
	parser.add_argument("--vlan", type=int, help="VLAN ID to query (1-4094)")
	return parser.parse_args()


def resolve_inventory_path(inventory_path: str) -> str:
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
	cmd = ["ansible-inventory", "-i", inventory_path, "--list"]
	proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
	inv = json.loads(proc.stdout)

	if group not in inv:
		raise ValueError(f"Group '{group}' not found in inventory")

	visited = set()

	def collect(group_name: str) -> set[str]:
		if group_name in visited:
			return set()
		visited.add(group_name)

		data = inv.get(group_name, {})
		hosts = set(data.get("hosts", []))
		for child in data.get("children", []):
			hosts.update(collect(child))
		return hosts

	hostvars = inv.get("_meta", {}).get("hostvars", {})
	result = []
	for host in sorted(collect(group)):
		ip = hostvars.get(host, {}).get("ansible_host", host)
		result.append((host, ip))
	return result


def get_output(response: dict) -> str:
	result = response.get("result")
	if isinstance(result, dict):
		if isinstance(result.get("output"), str):
			return result["output"]
		if isinstance(result.get("response"), str):
			return result["response"]
	if isinstance(response.get("output"), str):
		return response["output"]
	if isinstance(response.get("response"), str):
		return response["response"]
	return str(response)


def colorize(text: str, color: str) -> str:
	if not sys.stdout.isatty():
		return text
	return f"{color}{text}{RESET}"


def highlight_mac_entries(output: str) -> str:
	lines = []
	for line in output.splitlines():
		if MAC_ENTRY_RE.match(line):
			lines.append(colorize(line, GREEN))
		else:
			lines.append(line)
	return "\n".join(lines)


def ask_for_vlan() -> int:
	while True:
		value = input("Enter VLAN ID to query (1-4094): ").strip()
		if not value.isdigit():
			print("Invalid VLAN ID. Please enter a number between 1 and 4094.")
			continue
		vlan = int(value)
		if 1 <= vlan <= 4094:
			return vlan
		print("Invalid VLAN ID. Please enter a number between 1 and 4094.")


def validate_vlan(vlan: int) -> bool:
	return 1 <= vlan <= 4094


def main() -> int:
	args = parse_args()
	inventory_path = resolve_inventory_path(args.inventory)

	vlan_id = args.vlan if args.vlan is not None else ask_for_vlan()
	if not validate_vlan(vlan_id):
		print(f"Invalid VLAN ID: {vlan_id} (valid range: 1-4094)")
		return 2

	try:
		hosts = load_hosts(inventory_path, args.group)
	except Exception as exc:
		print(f"Inventory error: {exc}")
		return 2

	if not hosts:
		print("No hosts found.")
		return 2

	command = f"show mac address-table vlan {vlan_id}"
	failures = 0

	for inventory_host, ip in hosts:
		header = f"\n{'=' * 20} {inventory_host} ({ip}) {'=' * 20}"
		print(colorize(header, YELLOW))
		try:
			node = pyeapi.client.connect(
				transport=args.transport,
				host=ip,
				username=args.username,
				password=args.password,
				port=args.port,
				return_node=True,
				timeout=args.timeout,
			)
			response = node.enable([command], encoding="text")[0]
			print(highlight_mac_entries(get_output(response).rstrip()))
		except Exception as exc:
			failures += 1
			print(f"ERROR: {exc}")

	return 1 if failures else 0


if __name__ == "__main__":
	raise SystemExit(main())
