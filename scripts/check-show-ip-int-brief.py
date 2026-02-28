#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pyeapi


YELLOW = "\033[33m"
RESET = "\033[0m"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Collect 'show ip interface brief' output from all FABRIC devices via eAPI"
	)
	parser.add_argument("--inventory", default="inventory/inventory.yml", help="Path to Ansible inventory")
	parser.add_argument("--group", default="FABRIC", help="Inventory group to query")
	parser.add_argument("--username", default="admin", help="eAPI username")
	parser.add_argument("--password", default="admin", help="eAPI password")
	parser.add_argument("--transport", choices=["http", "https"], default="https", help="eAPI transport")
	parser.add_argument("--port", type=int, default=443, help="eAPI port")
	parser.add_argument("--timeout", type=int, default=30, help="eAPI connection timeout in seconds")
	parser.add_argument(
		"--output-dir",
		default="reports/show_ip_interface_brief",
		help="Directory where command outputs will be saved",
	)
	parser.add_argument(
		"--no-stdout",
		action="store_true",
		help="Do not print command output to stdout; save only to files",
	)
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


def resolve_output_dir(output_dir: str) -> Path:
	path = Path(output_dir)
	if path.is_absolute():
		return path

	script_dir = Path(__file__).resolve().parent
	repo_root = script_dir.parent
	return repo_root / output_dir


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


def main() -> int:
	args = parse_args()
	inventory_path = resolve_inventory_path(args.inventory)
	output_dir = resolve_output_dir(args.output_dir)
	timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
	snapshot_dir = output_dir / f"snapshot-{timestamp}"
	snapshot_dir.mkdir(parents=True, exist_ok=True)

	try:
		hosts = load_hosts(inventory_path, args.group)
	except Exception as exc:
		print(f"Inventory error: {exc}")
		return 2

	if not hosts:
		print("No hosts found.")
		return 2

	failures = 0
	summary_lines = []
	command = "show ip interface brief"

	for inventory_host, ip in hosts:
		headline = f"{'=' * 20} {inventory_host} ({ip}) {'=' * 20}"
		print(colorize(f"\n{headline}", YELLOW))
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
			device_output = get_output(response).rstrip() + "\n"

			host_file = snapshot_dir / f"{inventory_host}_show-ip-interface-brief.txt"
			host_file.write_text(device_output, encoding="utf-8")

			summary_lines.append(headline)
			summary_lines.append(device_output.rstrip())
			summary_lines.append("")

			if not args.no_stdout:
				print(device_output.rstrip())
		except Exception as exc:
			failures += 1
			error_message = f"ERROR: {exc}"
			print(error_message)
			(summary_dir_file := snapshot_dir / f"{inventory_host}_show-ip-interface-brief.txt").write_text(
				error_message + "\n", encoding="utf-8"
			)
			summary_lines.append(headline)
			summary_lines.append(error_message)
			summary_lines.append("")

	combined_file = snapshot_dir / "all-devices_show-ip-interface-brief.txt"
	combined_file.write_text("\n".join(summary_lines).rstrip() + "\n", encoding="utf-8")

	print(f"\nSaved snapshot directory: {snapshot_dir}")
	print(f"Combined output file: {combined_file}")

	return 1 if failures else 0


if __name__ == "__main__":
	raise SystemExit(main())
