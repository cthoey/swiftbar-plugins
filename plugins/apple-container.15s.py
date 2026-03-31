#!/usr/bin/env python3
# <xbar.title>Apple Container status</xbar.title>
# <xbar.version>v1.1</xbar.version>
# <xbar.author>OpenAI</xbar.author>
# <xbar.desc>Shows running Apple Container containers and live-ish resource stats in your macOS menu bar.</xbar.desc>
# <xbar.dependencies>python3,container</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.refreshOnOpen>false</swiftbar.refreshOnOpen>

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List

CONTAINER_BIN = shutil.which("container")
if not CONTAINER_BIN:
    for candidate in ("/opt/homebrew/bin/container", "/usr/local/bin/container"):
        if os.path.exists(candidate):
            CONTAINER_BIN = candidate
            break
if not CONTAINER_BIN:
    CONTAINER_BIN = "container"

CACHE_FILE = os.path.join(tempfile.gettempdir(), "swiftbar-apple-container-cpu.json")


def run(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    if cmd and cmd[0] == "container":
        cmd = [CONTAINER_BIN, *cmd[1:]]
    return subprocess.run(cmd, capture_output=True, text=True)


def human_bytes(n: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(n)
    for unit in units:
        if abs(value) < 1024.0 or unit == units[-1]:
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.2f} TiB"


def parse_cpu_percent(text: str) -> float:
    try:
        return float(text.replace("%", "").strip())
    except Exception:
        return 0.0


def shell_quote(s: str) -> str:
    return shlex.quote(s)


def swiftbar_action(executable: str, args: List[str], terminal: bool = False, refresh: bool = True) -> str:
    parts = [f"bash={shell_quote(executable)}"]
    for index, arg in enumerate(args):
        parts.append(f"param{index}={shell_quote(arg)}")
    parts.append(f"terminal={'true' if terminal else 'false'}")
    parts.append(f"refresh={'true' if refresh else 'false'}")
    return " ".join(parts)


def container_action(args: List[str], terminal: bool = False, refresh: bool = True) -> str:
    return swiftbar_action(CONTAINER_BIN, args, terminal=terminal, refresh=refresh)


def shell_action(command: str, terminal: bool = False, refresh: bool = True) -> str:
    return swiftbar_action("/bin/zsh", ["-lc", command], terminal=terminal, refresh=refresh)


def open_in_terminal(command: str) -> str:
    # Uses AppleScript so the command opens in a new Terminal tab/window.
    script = f'tell application "Terminal" to do script {json.dumps(command)}'
    return f"bash='/usr/bin/osascript' param0='-e' param1={shell_quote(script)} terminal=false refresh=false"


def get_containers(include_all: bool = False) -> List[Dict[str, Any]]:
    cmd = ["container", "list", "--format", "json"]
    if include_all:
        cmd.append("--all")
    cp = run(cmd)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or cp.stdout.strip() or "container list failed")
    data = json.loads(cp.stdout or "[]")
    if not isinstance(data, list):
        return []
    return data


def get_stats_json() -> Dict[str, Dict[str, Any]]:
    cp = run(["container", "stats", "--format", "json", "--no-stream"])
    if cp.returncode != 0:
        return {}
    try:
        data = json.loads(cp.stdout or "[]")
    except Exception:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for item in data:
        cid = item.get("id")
        if cid:
            out[cid] = item
    return out


def load_cpu_cache() -> Dict[str, Any]:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cpu_cache(stats_json: Dict[str, Dict[str, Any]]) -> None:
    payload = {
        "timestamp": time.time(),
        "cpuUsageUsec": {
            cid: float(item.get("cpuUsageUsec", 0) or 0)
            for cid, item in stats_json.items()
        },
    }
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except Exception:
        pass


def cpu_percents_from_stats(stats_json: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    cache = load_cpu_cache()
    previous_timestamp = float(cache.get("timestamp", 0) or 0)
    previous_cpu = cache.get("cpuUsageUsec") or {}
    now = time.time()
    elapsed_usec = max((now - previous_timestamp) * 1_000_000, 1.0)

    cpu_percents: Dict[str, float] = {}
    for cid, item in stats_json.items():
        current = float(item.get("cpuUsageUsec", 0) or 0)
        prior = float(previous_cpu.get(cid, current if previous_timestamp else 0) or 0)
        delta = max(current - prior, 0.0)
        cpu_percents[cid] = (delta / elapsed_usec) * 100.0 if previous_timestamp else 0.0

    save_cpu_cache(stats_json)
    return cpu_percents


def system_status() -> str:
    cp = run(["container", "system", "status"])
    if cp.returncode != 0:
        return "stopped"

    for line in cp.stdout.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) == 2 and parts[0] == "status":
            return parts[1]

    return "running"


def container_status(item: Dict[str, Any]) -> str:
    return str(item.get("status") or "unknown")


def published_ports(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    return item.get("configuration", {}).get("publishedPorts") or []


def port_summary(item: Dict[str, Any]) -> str:
    ports = published_ports(item)
    if not ports:
        return "—"

    summaries: List[str] = []
    for port in ports:
        host_address = port.get("hostAddress") or "127.0.0.1"
        host_port = port.get("hostPort")
        container_port = port.get("containerPort")
        proto = port.get("proto") or "tcp"
        if host_port and container_port:
            summaries.append(f"{host_address}:{host_port}->{container_port}/{proto}")

    return ", ".join(summaries) if summaries else "—"


def net_text(item: Dict[str, Any]) -> str:
    return f"{human_bytes(float(item.get('networkRxBytes', 0) or 0))} / {human_bytes(float(item.get('networkTxBytes', 0) or 0))}"


def block_text(item: Dict[str, Any]) -> str:
    return f"{human_bytes(float(item.get('blockReadBytes', 0) or 0))} / {human_bytes(float(item.get('blockWriteBytes', 0) or 0))}"


def memory_text(stats: Dict[str, Any], fallback_limit: Any = None) -> str:
    used = float(stats.get("memoryUsageBytes", 0) or 0)
    limit = float(stats.get("memoryLimitBytes", 0) or fallback_limit or 0)
    if limit:
        return f"{human_bytes(used)} / {human_bytes(limit)}"
    return human_bytes(used)


def header(all_containers: List[Dict[str, Any]], running: List[Dict[str, Any]], stats_json: Dict[str, Dict[str, Any]], cpu_percents: Dict[str, float]) -> str:
    count = len(running)
    stopped = len(all_containers) - count
    if count == 0:
        return f"⬢ 0 · {stopped} stopped" if stopped else "⬢ 0"
    total_mem = sum(float(stats_json.get(item_id(item), {}).get("memoryUsageBytes", 0) or 0) for item in running)
    total_cpu = sum(cpu_percents.get(item_id(item), 0.0) for item in running)
    if stopped:
        return f"⬢ {count} · {total_cpu:.0f}% · {human_bytes(total_mem)} · {stopped} stopped"
    return f"⬢ {count} · {total_cpu:.0f}% · {human_bytes(total_mem)}"


def item_id(item: Dict[str, Any]) -> str:
    return (
        item.get("configuration", {}).get("id")
        or item.get("id")
        or item.get("name")
        or "unknown"
    )


def item_ip(item: Dict[str, Any]) -> str:
    networks = item.get("networks") or []
    if not networks:
        return "—"
    addr = (
        networks[0].get("address")
        or networks[0].get("ipv4Address")
        or networks[0].get("ipv6Address")
    )
    return addr or "—"


def emit_error(title: str, detail: str) -> None:
    print(f"⬢ {title}")
    print("---")
    print(detail.replace("\n", " "))
    print("Refresh | refresh=true")


def main() -> int:
    try:
        status = system_status()
    except FileNotFoundError:
        emit_error("missing", "The `container` CLI was not found in PATH.")
        return 0
    except Exception as exc:
        emit_error("error", str(exc))
        return 0

    if status != "running":
        print("⬢ off")
        print("---")
        print("Apple Container system is stopped.")
        print(f"Start system | {container_action(['system', 'start'])}")
        print(f"System logs | {open_in_terminal('container system logs -f')}")
        print("Refresh | refresh=true")
        return 0

    try:
        all_containers = get_containers(include_all=True)
        running = [item for item in all_containers if container_status(item) == "running"]
        stats_json = get_stats_json()
        cpu_percents = cpu_percents_from_stats(stats_json)
        running_ids = [item_id(item) for item in running]
    except FileNotFoundError:
        emit_error("missing", "The `container` CLI was not found in PATH.")
        return 0
    except Exception as exc:
        emit_error("error", str(exc))
        return 0

    stopped = [item for item in all_containers if container_status(item) != "running"]

    print(header(all_containers, running, stats_json, cpu_percents))
    print("---")
    print(f"System: {status}")
    print(f"Running: {len(running)}")
    print(f"Stopped: {len(stopped)}")
    print(f"Total: {len(all_containers)}")
    total_mem = sum(float(stats_json.get(cid, {}).get("memoryUsageBytes", 0) or 0) for cid in running_ids)
    total_pids = sum(int(stats_json.get(cid, {}).get("numProcesses", 0) or 0) for cid in running_ids)
    total_rx = sum(float(stats_json.get(cid, {}).get("networkRxBytes", 0) or 0) for cid in running_ids)
    total_tx = sum(float(stats_json.get(cid, {}).get("networkTxBytes", 0) or 0) for cid in running_ids)
    total_read = sum(float(stats_json.get(cid, {}).get("blockReadBytes", 0) or 0) for cid in running_ids)
    total_write = sum(float(stats_json.get(cid, {}).get("blockWriteBytes", 0) or 0) for cid in running_ids)
    total_cpu = sum(cpu_percents.get(cid, 0.0) for cid in running_ids)

    print(f"Total CPU: {total_cpu:.2f}%")
    print(f"Total Memory: {human_bytes(total_mem)}")
    print(f"Total PIDs: {total_pids}")
    print(f"Total Net Rx/Tx: {human_bytes(total_rx)} / {human_bytes(total_tx)}")
    print(f"Total Disk R/W: {human_bytes(total_read)} / {human_bytes(total_write)}")
    print("Refresh | refresh=true")

    print("---")
    print("Actions")
    print(f"-- Stop system | {container_action(['system', 'stop'])}")
    print(f"-- Restart system | {shell_action(f'{shell_quote(CONTAINER_BIN)} system stop && {shell_quote(CONTAINER_BIN)} system start')}")
    if running_ids:
        print(f"-- Stop all running | {container_action(['stop', '--all'])}")
    if stopped:
        print(f"-- Prune stopped | {container_action(['prune'])}")
    print(f"-- System logs | {open_in_terminal('container system logs -f')}")
    print(f"-- System disk usage | {open_in_terminal('container system df')}")

    if not all_containers:
        return 0

    print("---")
    print("Running Containers")
    if not running_ids:
        print("-- None")
        print("---")

    for item in running:
        cid = item_id(item)
        sj = stats_json.get(cid, {})
        cfg = item.get("configuration", {})
        res = cfg.get("resources", {})
        mem_limit = sj.get("memoryLimitBytes") or res.get("memoryInBytes")
        cpus = res.get("cpus", "—")
        ip = item_ip(item)

        title = f"{cid} — {cpu_percents.get(cid, 0.0):.2f}% CPU, {memory_text(sj, mem_limit)}, {sj.get('numProcesses', '—')} pids"
        print(title)
        print("-- Status: running")
        print(f"-- IP: {ip}")
        print(f"-- Ports: {port_summary(item)}")
        limit_text = human_bytes(float(mem_limit)) if mem_limit else "—"
        print(f"-- Limit: {cpus} CPU / {limit_text}")
        print(f"-- Net: {net_text(sj)}")
        print(f"-- Disk: {block_text(sj)}")
        print(f"-- Stop | {container_action(['stop', cid])}")
        print(f"-- Restart | {shell_action(f'{shell_quote(CONTAINER_BIN)} stop {shell_quote(cid)} && {shell_quote(CONTAINER_BIN)} start {shell_quote(cid)}')}")
        print(f"-- Kill | {container_action(['kill', cid])}")
        print(f"-- Logs | {open_in_terminal(f'container logs -f {shell_quote(cid)}')}")
        print(f"-- Shell (sh) | {open_in_terminal(f'container exec -it {shell_quote(cid)} sh')}")
        print(f"-- Inspect | {open_in_terminal(f'container inspect {shell_quote(cid)} | python3 -m json.tool | less')}")
        print("---")

    if stopped:
        print("Stopped Containers")
        for item in stopped:
            cid = item_id(item)
            cfg = item.get("configuration", {})
            res = cfg.get("resources", {})
            mem_limit = res.get("memoryInBytes")
            cpus = res.get("cpus", "—")
            title = f"{cid} — stopped"
            print(title)
            print("-- Status: stopped")
            print(f"-- Ports: {port_summary(item)}")
            limit_text = human_bytes(float(mem_limit)) if mem_limit else "—"
            print(f"-- Limit: {cpus} CPU / {limit_text}")
            print(f"-- Start | {container_action(['start', cid])}")
            print(f"-- Delete | {container_action(['delete', cid])}")
            print(f"-- Inspect | {open_in_terminal(f'container inspect {shell_quote(cid)} | python3 -m json.tool | less')}")
            print("---")

    return 0


if __name__ == "__main__":
    sys.exit(main())
