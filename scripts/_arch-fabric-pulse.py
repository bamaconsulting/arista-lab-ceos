#!/usr/bin/env python3

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

import pyeapi


console = Console()


@dataclass
class Device:
    name: str
    host: str


@dataclass
class Snapshot:
    name: str
    model: str
    version: str
    uptime: str
    cpu: str
    temperature: str
    bgp: str
    mlag: str
    reachable: bool
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arista Fabric Pulse - health dashboard and drift warden")
    parser.add_argument("--inventory", default="inventory/inventory.yml", help="Ansible inventory path")
    parser.add_argument("--group", default="FABRIC", help="Inventory group to monitor")
    parser.add_argument("--username", default="admin", help="eAPI username")
    parser.add_argument("--password", default="admin", help="eAPI password")
    parser.add_argument("--port", type=int, default=443, help="eAPI TCP port")
    parser.add_argument("--insecure", action="store_true", help="Disable SSL verification")
    parser.add_argument("--transport", choices=["http", "https"], default="https", help="eAPI transport")
    parser.add_argument("--golden-dir", default="build/configs", help="Directory containing <hostname>.cfg golden configs")
    parser.add_argument(
        "--flash-dir",
        default="clab-dc1_fabric",
        help="Containerlab data dir containing <hostname>/flash for configure replace staging",
    )
    parser.add_argument("--watch", action="store_true", help="Live refresh dashboard until Ctrl+C")
    parser.add_argument("--interval", type=float, default=3.0, help="Refresh interval for --watch")
    parser.add_argument("--no-restore", action="store_true", help="Detect/report drift but never ask to restore")
    parser.add_argument("--max-diff-lines", type=int, default=120, help="Max diff lines shown per device")
    return parser.parse_args()


def load_inventory_devices(inventory_path: str, group: str) -> list[Device]:
    command = ["ansible-inventory", "-i", inventory_path, "--list"]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to run ansible-inventory: {proc.stderr.strip()}")

    inv = json.loads(proc.stdout)
    if group not in inv:
        raise RuntimeError(f"Group '{group}' not found in inventory")

    def collect_hosts(group_name: str, seen: set[str] | None = None) -> set[str]:
        if seen is None:
            seen = set()
        if group_name in seen:
            return set()
        seen.add(group_name)

        group_data = inv.get(group_name, {})
        hosts = set(group_data.get("hosts", []))
        for child in group_data.get("children", []):
            hosts.update(collect_hosts(child, seen))
        return hosts

    group_hosts = sorted(collect_hosts(group))
    hostvars = inv.get("_meta", {}).get("hostvars", {})
    devices: list[Device] = []
    for hostname in group_hosts:
        host_ip = hostvars.get(hostname, {}).get("ansible_host", hostname)
        devices.append(Device(name=hostname, host=host_ip))
    return devices


def node_for_device(device: Device, args: argparse.Namespace):
    return pyeapi.client.connect(
        transport=args.transport,
        host=device.host,
        username=args.username,
        password=args.password,
        port=args.port,
        return_node=True,
        timeout=30,
    )


def command_json(node: Any, command: str) -> dict[str, Any]:
    response = node.enable([command])[0]
    if isinstance(response, dict) and "result" in response and isinstance(response["result"], dict):
        return response["result"]
    if isinstance(response, dict):
        return response
    return {}


def command_text(node: Any, command: str) -> str:
    response = node.enable([command], encoding="text")[0]
    if isinstance(response, dict):
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


def format_uptime(seconds: Any) -> str:
    if not isinstance(seconds, int):
        return "n/a"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"


def read_cpu(node: Any) -> str:
    try:
        output = command_json(node, "show processes top once")
        for key in ("cpu", "cpuUtilization", "cpuTotal"):
            value = output.get(key)
            if isinstance(value, (int, float)):
                return f"{value:.1f}%"
    except Exception:
        return "n/a"
    return "n/a"


def read_temperature(node: Any) -> str:
    try:
        output = command_json(node, "show system environment temperature")
        temperatures = []
        for section in ("cardSlots", "powerSupplySlots", "tempSensors"):
            items = output.get(section, {})
            if isinstance(items, dict):
                for _, item in items.items():
                    value = item.get("currentTemperature")
                    if isinstance(value, (int, float)):
                        temperatures.append(float(value))
        if temperatures:
            return f"{max(temperatures):.1f}C"
    except Exception:
        return "n/a"
    return "n/a"


def read_bgp_status(node: Any) -> str:
    try:
        output = command_json(node, "show ip bgp summary")
        vrfs = output.get("vrfs", {})
        established = 0
        total = 0
        for vrf_data in vrfs.values():
            peers = vrf_data.get("peers", {})
            total += len(peers)
            for peer_data in peers.values():
                if peer_data.get("peerState") == "Established":
                    established += 1
        if total == 0:
            return "n/a"
        return f"{established}/{total} up"
    except Exception:
        return "n/a"


def read_mlag_status(node: Any) -> str:
    try:
        output = command_json(node, "show mlag")
        state = output.get("state") or output.get("mlagState")
        if state:
            return str(state)
        return "disabled"
    except Exception:
        return "n/a"


def health_color(cpu_text: str, temp_text: str) -> str:
    cpu_value = None
    temp_value = None
    try:
        cpu_value = float(cpu_text.rstrip("%"))
    except Exception:
        pass
    try:
        temp_value = float(temp_text.rstrip("C"))
    except Exception:
        pass

    if cpu_value is not None and cpu_value >= 80:
        return "red"
    if temp_value is not None and temp_value >= 80:
        return "red"
    if cpu_value is None and temp_value is None:
        return "yellow"
    return "green"


def mlag_color(state: str) -> str:
    normalized = state.lower()
    if normalized in {"active", "enabled"}:
        return "green"
    if normalized in {"n/a", "disabled"}:
        return "yellow"
    return "red"


def collect_snapshot(device: Device, args: argparse.Namespace) -> Snapshot:
    try:
        node = node_for_device(device, args)
        version = command_json(node, "show version")
        cpu = read_cpu(node)
        temp = read_temperature(node)
        bgp = read_bgp_status(node)
        mlag = read_mlag_status(node)
        return Snapshot(
            name=device.name,
            model=str(version.get("modelName", "n/a")),
            version=str(version.get("version", "n/a")),
            uptime=format_uptime(version.get("uptime")),
            cpu=cpu,
            temperature=temp,
            bgp=bgp,
            mlag=mlag,
            reachable=True,
        )
    except Exception as exc:
        return Snapshot(
            name=device.name,
            model="n/a",
            version="n/a",
            uptime="n/a",
            cpu="n/a",
            temperature="n/a",
            bgp="n/a",
            mlag="n/a",
            reachable=False,
            error=str(exc),
        )


def build_dashboard(snapshots: list[Snapshot]) -> Table:
    table = Table(title="Arista Fabric Pulse", box=box.SIMPLE_HEAVY)
    table.add_column("Device", style="cyan", no_wrap=True)
    table.add_column("Model")
    table.add_column("Version")
    table.add_column("Uptime")
    table.add_column("CPU")
    table.add_column("Temp")
    table.add_column("BGP")
    table.add_column("MLAG")
    table.add_column("Status")

    for snap in snapshots:
        if not snap.reachable:
            table.add_row(
                snap.name,
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                f"[red]UNREACHABLE[/red] {snap.error}",
            )
            continue

        health = health_color(snap.cpu, snap.temperature)
        bgp_style = "green" if snap.bgp.endswith("up") and not snap.bgp.startswith("0/") else "yellow"
        table.add_row(
            snap.name,
            snap.model,
            snap.version,
            snap.uptime,
            f"[{health}]{snap.cpu}[/{health}]",
            f"[{health}]{snap.temperature}[/{health}]",
            f"[{bgp_style}]{snap.bgp}[/{bgp_style}]",
            f"[{mlag_color(snap.mlag)}]{snap.mlag}[/{mlag_color(snap.mlag)}]",
            "[bold green]OK[/bold green]",
        )
    return table


def golden_file_path(golden_dir: Path, hostname: str) -> Path:
    return golden_dir / f"{hostname}.cfg"


def running_config(node: Any) -> str:
    text = command_text(node, "show running-config")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip() + "\n"


def load_golden_config(path: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8").splitlines()).strip() + "\n"


def config_diff(golden: str, running: str, hostname: str) -> list[str]:
    return list(
        difflib.unified_diff(
            golden.splitlines(),
            running.splitlines(),
            fromfile=f"golden/{hostname}.cfg",
            tofile=f"running/{hostname}",
            lineterm="",
            n=2,
        )
    )


def detect_drift(devices: list[Device], args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    golden_dir = Path(args.golden_dir)
    results: dict[str, dict[str, Any]] = {}
    for device in devices:
        result: dict[str, Any] = {
            "drift": False,
            "reason": "",
            "diff": [],
            "golden_path": str(golden_file_path(golden_dir, device.name)),
        }
        path = golden_file_path(golden_dir, device.name)
        if not path.exists():
            result["reason"] = "Golden config missing"
            results[device.name] = result
            continue

        try:
            node = node_for_device(device, args)
            running = running_config(node)
            golden = load_golden_config(path)
            diff = config_diff(golden, running, device.name)
            result["diff"] = diff
            result["drift"] = len(diff) > 0
        except Exception as exc:
            result["reason"] = f"Error reading running-config: {exc}"
        results[device.name] = result
    return results


def build_drift_table(drift_data: dict[str, dict[str, Any]]) -> Table:
    table = Table(title="Drift Warden", box=box.SIMPLE_HEAVY)
    table.add_column("Device", style="cyan")
    table.add_column("Drift")
    table.add_column("Reason")
    table.add_column("Golden")
    for device, info in drift_data.items():
        if info["drift"]:
            state = "[bold red]DRIFT[/bold red]"
            reason = f"{len(info['diff'])} diff lines"
        elif info["reason"]:
            state = "[yellow]UNKNOWN[/yellow]"
            reason = info["reason"]
        else:
            state = "[green]CLEAN[/green]"
            reason = "No drift"
        table.add_row(device, state, reason, info["golden_path"])
    return table


def stage_golden_to_flash(flash_root: Path, hostname: str, golden_file: Path) -> str:
    flash_dir = flash_root / hostname / "flash"
    flash_dir.mkdir(parents=True, exist_ok=True)
    staged_name = f"golden-{hostname}.cfg"
    staged_path = flash_dir / staged_name
    shutil.copyfile(golden_file, staged_path)
    return staged_name


def restore_golden(device: Device, args: argparse.Namespace) -> tuple[bool, str]:
    path = golden_file_path(Path(args.golden_dir), device.name)
    if not path.exists():
        return False, f"Golden config not found: {path}"

    try:
        staged_name = stage_golden_to_flash(Path(args.flash_dir), device.name, path)
        node = node_for_device(device, args)
        node.enable([f"configure replace flash:{staged_name}", "write memory"])
        return True, f"Restored from flash:{staged_name}"
    except Exception as exc:
        return False, str(exc)


def display_diff(device: str, diff_lines: list[str], max_lines: int) -> None:
    if not diff_lines:
        return
    preview = diff_lines[:max_lines]
    suffix = ""
    if len(diff_lines) > max_lines:
        suffix = f"\n... ({len(diff_lines) - max_lines} more lines)"
    body = "\n".join(preview) + suffix
    console.print(Panel(body, title=f"Diff: {device}", border_style="red"))


def main() -> int:
    args = parse_args()

    console.print("[bold cyan]Starting Arista Fabric Pulse[/bold cyan]")
    try:
        devices = load_inventory_devices(args.inventory, args.group)
    except Exception as exc:
        console.print(f"[bold red]Inventory load failed:[/bold red] {exc}")
        return 2

    if not devices:
        console.print("[bold red]No devices found in selected inventory group.[/bold red]")
        return 2

    if args.watch:
        with Live(console=console, refresh_per_second=max(1, int(1 / max(0.1, args.interval)))) as live:
            try:
                while True:
                    snapshots = [collect_snapshot(device, args) for device in devices]
                    live.update(build_dashboard(snapshots))
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                pass
    else:
        snapshots = [collect_snapshot(device, args) for device in devices]
        console.print(build_dashboard(snapshots))

    console.print("\n[bold magenta]Detect -> Report[/bold magenta]")
    drift_data = detect_drift(devices, args)
    console.print(build_drift_table(drift_data))

    drifted = [d for d in devices if drift_data[d.name]["drift"]]
    for device in drifted:
        display_diff(device.name, drift_data[device.name]["diff"], args.max_diff_lines)

    if args.no_restore or not drifted:
        if drifted:
            console.print("[yellow]Drift detected. Restore disabled by --no-restore.[/yellow]")
            return 1
        console.print("[green]No drift detected.[/green]")
        return 0

    prompt = "[bold red]Drift detected! Restore to Golden State?[/bold red]"
    if not Confirm.ask(prompt, default=False):
        console.print("[yellow]Restore cancelled by user.[/yellow]")
        return 1

    console.print("\n[bold magenta]Fix -> Verify[/bold magenta]")
    all_ok = True
    for device in drifted:
        ok, message = restore_golden(device, args)
        if ok:
            console.print(f"[green]{device.name}[/green]: {message}")
        else:
            all_ok = False
            console.print(f"[red]{device.name}[/red]: {message}")

    post_drift = detect_drift(drifted, args)
    console.print(build_drift_table(post_drift))
    remaining = [name for name, info in post_drift.items() if info["drift"]]
    if remaining:
        all_ok = False
        console.print(f"[red]Drift still present on: {', '.join(remaining)}[/red]")
    else:
        console.print("[bold green]Fabric restored to Golden State.[/bold green]")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
