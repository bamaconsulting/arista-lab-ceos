#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
from pathlib import Path

import pyeapi


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Ping all Loopback0 addresses between leafs")
	parser.add_argument("--inventory", default="inventory/inventory.yml", help="Path to Ansible inventory")
	parser.add_argument("--group", default="DC1_L3_LEAVES", help="Inventory group with leaf devices")
	parser.add_argument("--username", default="admin", help="eAPI username")
	parser.add_argument("--password", default="admin", help="eAPI password")
	parser.add_argument("--transport", choices=["http", "https"], default="https", help="eAPI transport")
	parser.add_argument("--port", type=int, default=443, help="eAPI port")
	parser.add_argument("--repeat", type=int, default=3, help="Ping repeat count")
	parser.add_argument("--timeout", type=int, default=2, help="Ping timeout in seconds")
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


def connect_node(ip: str, args: argparse.Namespace):
	return pyeapi.client.connect(
		transport=args.transport,
		host=ip,
		username=args.username,
		password=args.password,
		port=args.port,
		return_node=True,
		timeout=30,
	)


def get_text_output(response: dict) -> str:
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


def get_loopback0_ip(node) -> str:
	response = node.enable(["show ip interface Loopback0"], encoding="text")[0]
	output = get_text_output(response)
	match = re.search(r"Internet address is\s+(\d+\.\d+\.\d+\.\d+)/\d+", output)
	if not match:
		raise ValueError("Unable to parse Loopback0 IP")
	return match.group(1)


def parse_ping_success(output: str) -> tuple[bool, str]:
	match = re.search(r"Success rate is\s+(\d+) percent\s+\((\d+)/(\d+)\)", output)
	if not match:
		linux_match = re.search(
			r"(\d+) packets transmitted,\s*(\d+) received,\s*(\d+)% packet loss",
			output,
			re.IGNORECASE,
		)
		if linux_match:
			tx = int(linux_match.group(1))
			rx = int(linux_match.group(2))
			loss = int(linux_match.group(3))
			ok = tx > 0 and loss == 0 and rx == tx
			return ok, f"Packet loss {loss}% ({rx}/{tx})"
		return False, "Could not parse ping result"

	percent = int(match.group(1))
	ok = percent == 100
	return ok, f"Success rate {percent}% ({match.group(2)}/{match.group(3)})"


def main() -> int:
	args = parse_args()
	inventory_path = resolve_inventory_path(args.inventory)

	try:
		hosts = load_hosts(inventory_path, args.group)
	except Exception as exc:
		print(f"Inventory error: {exc}")
		return 2

	if len(hosts) < 2:
		print("Need at least two leafs in the selected group.")
		return 2

	leaf_nodes = {}
	loopback0_ips = {}
	failures = 0

	print("Collecting Loopback0 IPs...")
	for leaf, ip in hosts:
		try:
			node = connect_node(ip, args)
			leaf_nodes[leaf] = node
			loopback0_ip = get_loopback0_ip(node)
			loopback0_ips[leaf] = loopback0_ip
			print(f"  {leaf:<12} -> {loopback0_ip}")
		except Exception as exc:
			failures += 1
			print(f"  {leaf:<12} -> ERROR: {exc}")

	if len(loopback0_ips) < 2:
		print("Not enough valid Loopback0 addresses to run matrix ping.")
		return 2

	print("\nPinging Loopback0-to-Loopback0 between all leafs:")
	print("-" * 78)
	print(f"{'Source':<14} {'Source Lo0':<16} {'Destination':<14} {'Dest Lo0':<16} Result")
	print("-" * 78)

	for src_leaf, src_node in leaf_nodes.items():
		if src_leaf not in loopback0_ips:
			continue
		for dst_leaf, dst_loopback0_ip in loopback0_ips.items():
			if src_leaf == dst_leaf:
				continue
			try:
				cmd = f"ping {dst_loopback0_ip} source Loopback0 repeat {args.repeat} timeout {args.timeout}"
				response = src_node.enable([cmd], encoding="text")[0]
				output = get_text_output(response)
				ok, message = parse_ping_success(output)
				state = "PASS" if ok else "FAIL"
				if not ok:
					failures += 1
				print(f"{src_leaf:<14} {loopback0_ips[src_leaf]:<16} {dst_leaf:<14} {dst_loopback0_ip:<16} {state} - {message}")
			except Exception as exc:
				failures += 1
				print(f"{src_leaf:<14} {loopback0_ips[src_leaf]:<16} {dst_leaf:<14} {dst_loopback0_ip:<16} ERROR - {exc}")

	print("-" * 78)
	if failures:
		print(f"Completed with {failures} issue(s).")
		return 1

	print("All Loopback0-to-Loopback0 pings passed.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())

