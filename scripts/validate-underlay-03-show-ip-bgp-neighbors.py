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

HIGHLIGHT_TERMS = [
	"VRF default",
	"peer-group IPv4-UNDERLAY-PEERS",
	"Multiprotocol IPv4 Unicast",
	"maximum total number of routes is",
	"MD5 authentication",
	"BGP neighbor is",
	"Established",
]


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Interactive BGP neighbor check: choose device from inventory, "
			"discover neighbors from 'show ip bgp summary', and run "
			"'show ip bgp neighbors A.B.C.D'"
		)
	)
	parser.add_argument("--inventory", default="inventory/inventory.yml", help="Path to Ansible inventory")
	parser.add_argument("--group", default="FABRIC", help="Inventory group to query")
	parser.add_argument("--username", default="admin", help="eAPI username")
	parser.add_argument("--password", default="admin", help="eAPI password")
	parser.add_argument("--transport", choices=["http", "https"], default="https", help="eAPI transport")
	parser.add_argument("--port", type=int, default=443, help="eAPI port")
	parser.add_argument("--timeout", type=int, default=30, help="eAPI connection timeout in seconds")
	parser.add_argument("--device", help="Inventory hostname (optional, skips interactive device selection)")
	parser.add_argument("--neighbor", help="BGP neighbor IP (optional, skips interactive neighbor selection)")
	return parser.parse_args()


def colorize(text: str, color: str) -> str:
	if not sys.stdout.isatty():
		return text
	return f"{color}{text}{RESET}"


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


def host_role(hostname: str) -> str:
	low = hostname.lower()
	if "leaf" in low:
		return "leaf"
	if "spine" in low:
		return "spine"
	return "other"


def parse_bgp_neighbors(summary_output: str) -> list[tuple[str, str]]:
	neighbors = []
	seen = set()
	pattern = re.compile(r"^\s*(.*?)\s+(\d{1,3}(?:\.\d{1,3}){3})\s+\d+\s+\d+\b")
	for line in summary_output.splitlines():
		match = pattern.search(line)
		if not match:
			continue
		description = match.group(1).strip() or "(no description)"
		ip = match.group(2)
		if ip not in seen:
			seen.add(ip)
			neighbors.append((description, ip))
	return neighbors


def highlight_matching_lines(output: str, terms: list[str]) -> str:
	highlighted = []
	for line in output.splitlines():
		if any(term in line for term in terms):
			highlighted.append(colorize(line, GREEN))
		else:
			highlighted.append(line)
	return "\n".join(highlighted)


def choose_option(prompt: str, options: list[str]) -> str:
	while True:
		choice = input(prompt).strip()
		if not choice.isdigit():
			print("Enter a number from the list.")
			continue
		idx = int(choice)
		if idx < 1 or idx > len(options):
			print(f"Number out of range 1-{len(options)}.")
			continue
		return options[idx - 1]


def choose_device_interactively(hosts: list[tuple[str, str]]) -> tuple[str, str]:
	role_choices = ["leaf", "spine", "all"]
	print("\nSelect device type:")
	for index, role in enumerate(role_choices, start=1):
		print(f"[{index}] {role}")
	selected_role = choose_option("Enter device type number: ", role_choices)

	if selected_role == "all":
		filtered = hosts
	else:
		filtered = [item for item in hosts if host_role(item[0]) == selected_role]

	if not filtered:
		raise ValueError(f"No devices of type '{selected_role}' found in inventory")

	device_options = []
	print("\nSelect device:")
	for index, (host, ip) in enumerate(filtered, start=1):
		label = f"{host} ({ip})"
		device_options.append(label)
		print(f"[{index}] {label}")

	selected_label = choose_option("Enter device number: ", device_options)
	for host, ip in filtered:
		if selected_label == f"{host} ({ip})":
			return host, ip

	raise ValueError("Unable to match selected device")


def find_device_by_name(hosts: list[tuple[str, str]], device_name: str) -> tuple[str, str]:
	for host, ip in hosts:
		if host == device_name:
			return host, ip
	raise ValueError(f"Device '{device_name}' does not exist in inventory")


def choose_neighbor_interactively(neighbors: list[tuple[str, str]]) -> str:
	print("\nDiscovered BGP neighbors:")
	options = []
	for index, (description, ip) in enumerate(neighbors, start=1):
		label = f"Description: {description} | IP: {ip}"
		options.append(label)
		print(f"[{index}] {label}")
	selected_label = choose_option("Enter BGP neighbor number: ", options)
	for description, ip in neighbors:
		if selected_label == f"Description: {description} | IP: {ip}":
			return ip
	raise ValueError("Unable to match selected BGP neighbor")


def main() -> int:
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

	try:
		if args.device:
			selected_host, selected_ip = find_device_by_name(hosts, args.device)
		else:
			selected_host, selected_ip = choose_device_interactively(hosts)
	except Exception as exc:
		print(f"Device selection error: {exc}")
		return 2

	header = f"\n{'=' * 20} {selected_host} ({selected_ip}) {'=' * 20}"
	print(colorize(header, YELLOW))

	try:
		node = pyeapi.client.connect(
			transport=args.transport,
			host=selected_ip,
			username=args.username,
			password=args.password,
			port=args.port,
			return_node=True,
			timeout=args.timeout,
		)
	except Exception as exc:
		print(f"eAPI connection error: {exc}")
		return 1

	try:
		summary_response = node.enable(["show ip bgp summary"], encoding="text")[0]
		summary_output = get_output(summary_response).rstrip()
	except Exception as exc:
		print(f"Execution error for 'show ip bgp summary': {exc}")
		return 1

	print("\nOutput from 'show ip bgp summary':")
	print(summary_output)

	neighbors = parse_bgp_neighbors(summary_output)
	if not neighbors:
		print("No BGP neighbors detected based on 'show ip bgp summary'.")
		return 1

	neighbor_ips = [ip for _, ip in neighbors]

	neighbor_ip = args.neighbor
	if neighbor_ip:
		if neighbor_ip not in neighbor_ips:
			print(f"Provided neighbor {neighbor_ip} is not present in discovered list: {', '.join(neighbor_ips)}")
			return 2
	else:
		neighbor_ip = choose_neighbor_interactively(neighbors)

	command = f"show ip bgp neighbors {neighbor_ip}"
	print(f"\nRunning: {command}")

	try:
		neighbor_response = node.enable([command], encoding="text")[0]
		print("\nResult:")
		neighbor_output = get_output(neighbor_response).rstrip()
		print(highlight_matching_lines(neighbor_output, HIGHLIGHT_TERMS))
	except Exception as exc:
		print(f"Execution error for '{command}': {exc}")
		return 1

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
