#!/usr/bin/env python3
# <xbar.title>Local Kubernetes</xbar.title>
# <xbar.version>v1.0.0</xbar.version>
# <xbar.author>OpenAI</xbar.author>
# <xbar.desc>Monitor and manage a local Kubernetes cluster running on Colima and kind.</xbar.desc>
# <xbar.dependencies>python3,kubectl,colima,kind,docker</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.refreshOnOpen>false</swiftbar.refreshOnOpen>

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

COLOR_OK = "#2a9d8f"
COLOR_WARN = "#ffb703"
COLOR_BAD = "#d7263d"
COLOR_OFF = "#6c757d"
SUBPROCESS_TIMEOUT = 4.0
CACHE_PATH = Path(tempfile.gettempdir()) / "swiftbar-kube-local-cache.json"
DEFAULT_CONTEXT = os.environ.get("KUBE_LOCAL_CONTEXT", "kind-kind")
DEFAULT_CLUSTER_NAME = os.environ.get("KUBE_LOCAL_CLUSTER_NAME", "kind")
GUIDE_PATH = Path(
    os.environ.get(
        "KUBE_LOCAL_GUIDE_PATH",
        "/Users/choey/Documents/10-projects/kubernetes/README.md",
    )
).expanduser()


def find_bin(name: str, *fallbacks: str) -> str:
    path = shutil.which(name)
    if path:
        return path
    for candidate in fallbacks:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return name


KUBECTL_BIN = find_bin("kubectl", "/opt/homebrew/bin/kubectl", "/usr/local/bin/kubectl")
COLIMA_BIN = find_bin("colima", "/opt/homebrew/bin/colima", "/usr/local/bin/colima")
KIND_BIN = find_bin("kind", "/opt/homebrew/bin/kind", "/usr/local/bin/kind")
DOCKER_BIN = find_bin("docker", "/opt/homebrew/bin/docker", "/usr/local/bin/docker")
K9S_BIN = find_bin("k9s", "/opt/homebrew/bin/k9s", "/usr/local/bin/k9s")


def run(cmd: list[str], timeout: float = SUBPROCESS_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={
            **os.environ,
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
    )


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def shell_join(parts: list[str]) -> str:
    return " ".join(shell_quote(part) for part in parts)


def swiftbar_action(
    executable: str,
    args: list[str],
    *,
    terminal: bool = False,
    refresh: bool = True,
) -> str:
    pieces = [f"bash={shell_quote(executable)}"]
    for index, arg in enumerate(args):
        pieces.append(f"param{index}={shell_quote(arg)}")
    pieces.append(f"terminal={'true' if terminal else 'false'}")
    pieces.append(f"refresh={'true' if refresh else 'false'}")
    return " ".join(pieces)


def shell_action(command: str, *, terminal: bool = False, refresh: bool = True) -> str:
    return swiftbar_action("/bin/zsh", ["-lc", command], terminal=terminal, refresh=refresh)


def open_in_terminal(command: str) -> str:
    script = f'tell application "Terminal" to do script {json.dumps(command)}'
    return swiftbar_action("/usr/bin/osascript", ["-e", script], terminal=False, refresh=False)


def open_path(path: Path) -> str:
    return swiftbar_action("/usr/bin/open", [str(path)], terminal=False, refresh=False)


def load_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def load_cache() -> dict[str, Any]:
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_cache(snapshot: dict[str, Any]) -> None:
    payload = {"saved_at": time.time(), "snapshot": snapshot}
    try:
        CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


def relative_age(timestamp: float | None) -> str:
    if timestamp is None:
        return "unknown"
    delta = max(int(time.time() - timestamp), 0)
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def bool_label(value: bool) -> str:
    return "yes" if value else "no"


def render_header(snapshot: dict[str, Any], stale_age: float | None = None) -> None:
    if not snapshot.get("colima_running"):
        print(f"⎈ OFF | color={COLOR_OFF}")
        return

    if not snapshot.get("context"):
        print(f"⎈ RUNTIME | color={COLOR_WARN}")
        return

    if not snapshot.get("cluster_reachable"):
        label = "DOWN" if snapshot.get("kind_cluster_exists") else "NOCLUSTER"
        if stale_age is not None:
            label = f"{label} stale"
        color = COLOR_BAD if snapshot.get("kind_cluster_exists") else COLOR_WARN
        print(f"⎈ {label} | color={color}")
        return

    ready = snapshot.get("ready_nodes", 0)
    total = snapshot.get("node_count", 0)
    bad = snapshot.get("problem_pod_count", 0)
    header = f"⎈ {ready}/{total}N"
    if bad:
        header += f" {bad}!"
    else:
        header += " OK"
    color = COLOR_BAD if bad else COLOR_OK
    if stale_age is not None:
        header += " stale"
        color = COLOR_WARN
    print(f"{header} | color={color}")


def pod_reason(pod: dict[str, Any]) -> str:
    status = pod.get("status") or {}
    phase = str(status.get("phase") or "Unknown")
    for state in status.get("containerStatuses") or []:
        waiting = ((state.get("state") or {}).get("waiting") or {})
        terminated = ((state.get("state") or {}).get("terminated") or {})
        if waiting.get("reason"):
            return str(waiting.get("reason"))
        if terminated.get("reason"):
            return str(terminated.get("reason"))
    return phase


def pod_restart_count(pod: dict[str, Any]) -> int:
    statuses = pod.get("status", {}).get("containerStatuses") or []
    total = 0
    for item in statuses:
        try:
            total += int(item.get("restartCount", 0) or 0)
        except Exception:
            continue
    return total


def pod_is_problem(pod: dict[str, Any]) -> bool:
    phase = str((pod.get("status") or {}).get("phase") or "")
    if phase in {"Pending", "Failed", "Unknown"}:
        return True
    if phase == "Succeeded":
        return False
    if pod_restart_count(pod) > 0:
        return True
    for state in (pod.get("status", {}).get("containerStatuses") or []):
        waiting = ((state.get("state") or {}).get("waiting") or {})
        if waiting.get("reason") in {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError"}:
            return True
    return False


def summarize_pods(pods: list[dict[str, Any]]) -> dict[str, Any]:
    phases = {"Running": 0, "Pending": 0, "Succeeded": 0, "Failed": 0, "Unknown": 0}
    problems: list[dict[str, Any]] = []
    for pod in pods:
        phase = str((pod.get("status") or {}).get("phase") or "Unknown")
        phases[phase] = phases.get(phase, 0) + 1
        if pod_is_problem(pod):
            metadata = pod.get("metadata") or {}
            problems.append(
                {
                    "namespace": str(metadata.get("namespace") or "default"),
                    "name": str(metadata.get("name") or "unknown"),
                    "reason": pod_reason(pod),
                    "restarts": pod_restart_count(pod),
                }
            )
    return {"phases": phases, "problems": problems}


def count_ready_nodes(nodes: list[dict[str, Any]]) -> tuple[int, int]:
    ready = 0
    for node in nodes:
        for condition in (node.get("status", {}).get("conditions") or []):
            if condition.get("type") == "Ready" and condition.get("status") == "True":
                ready += 1
                break
    return ready, len(nodes)


def current_context() -> str | None:
    try:
        cp = run([KUBECTL_BIN, "config", "current-context"])
    except Exception:
        return None
    if cp.returncode != 0:
        return None
    text = cp.stdout.strip()
    return text or None


def kind_clusters() -> list[str]:
    try:
        cp = run([KIND_BIN, "get", "clusters"])
    except Exception:
        return []
    if cp.returncode != 0:
        return []
    return [line.strip() for line in cp.stdout.splitlines() if line.strip()]


def colima_running() -> tuple[bool, str]:
    try:
        cp = run([COLIMA_BIN, "status"])
    except Exception as exc:
        return False, str(exc)
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout).strip()
        return False, detail or "not running"
    return True, cp.stdout.strip()


def cluster_snapshot() -> dict[str, Any]:
    colima_ok, colima_detail = colima_running()
    context = current_context()
    clusters = kind_clusters()
    kind_exists = DEFAULT_CLUSTER_NAME in clusters

    snapshot: dict[str, Any] = {
        "colima_running": colima_ok,
        "colima_detail": colima_detail,
        "context": context,
        "expected_context": DEFAULT_CONTEXT,
        "kind_cluster_exists": kind_exists,
        "kind_clusters": clusters,
        "cluster_reachable": False,
        "node_count": 0,
        "ready_nodes": 0,
        "problem_pod_count": 0,
        "pod_phases": {},
        "problem_pods": [],
        "captured_at": time.time(),
        "kubectl_error": "",
    }

    if not colima_ok:
        return snapshot

    try:
        nodes_cp = run([KUBECTL_BIN, "--context", DEFAULT_CONTEXT, "get", "nodes", "-o", "json"])
        pods_cp = run([KUBECTL_BIN, "--context", DEFAULT_CONTEXT, "get", "pods", "-A", "-o", "json"])
    except Exception as exc:
        snapshot["kubectl_error"] = str(exc)
        return snapshot

    if nodes_cp.returncode != 0:
        snapshot["kubectl_error"] = (nodes_cp.stderr or nodes_cp.stdout).strip()
        return snapshot
    if pods_cp.returncode != 0:
        snapshot["kubectl_error"] = (pods_cp.stderr or pods_cp.stdout).strip()
        return snapshot

    nodes_json = load_json(nodes_cp.stdout) or {}
    pods_json = load_json(pods_cp.stdout) or {}
    nodes = nodes_json.get("items") or []
    pods = pods_json.get("items") or []
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(pods, list):
        pods = []

    ready_nodes, node_count = count_ready_nodes(nodes)
    pod_summary = summarize_pods(pods)
    snapshot.update(
        {
            "cluster_reachable": True,
            "node_count": node_count,
            "ready_nodes": ready_nodes,
            "problem_pod_count": len(pod_summary["problems"]),
            "pod_phases": pod_summary["phases"],
            "problem_pods": pod_summary["problems"],
        }
    )
    return snapshot


def print_section(title: str) -> None:
    print("---")
    print(title)


def print_refresh() -> None:
    print("Refresh Now | refresh=true")


def action_commands() -> dict[str, str]:
    return {
        "start_colima": shell_join([COLIMA_BIN, "start", "--vm-type", "vz", "--cpu", "4", "--memory", "6", "--disk", "40"]),
        "stop_colima": shell_join([COLIMA_BIN, "stop"]),
        "create_kind": shell_join([KIND_BIN, "create", "cluster", "--wait", "60s"]),
        "delete_kind": shell_join([KIND_BIN, "delete", "cluster"]),
        "docker_ps": shell_join([DOCKER_BIN, "ps"]),
        "get_nodes": shell_join([KUBECTL_BIN, "--context", DEFAULT_CONTEXT, "get", "nodes", "-o", "wide"]),
        "get_pods": shell_join([KUBECTL_BIN, "--context", DEFAULT_CONTEXT, "get", "pods", "-A"]),
        "get_events": shell_join(
            [KUBECTL_BIN, "--context", DEFAULT_CONTEXT, "get", "events", "-A", "--sort-by=.lastTimestamp"]
        ),
        "cluster_info": shell_join([KUBECTL_BIN, "--context", DEFAULT_CONTEXT, "cluster-info"]),
        "use_context": shell_join([KUBECTL_BIN, "config", "use-context", DEFAULT_CONTEXT]),
        "k9s": shell_join([K9S_BIN]),
    }


def render(snapshot: dict[str, Any], cache_age: float | None = None) -> None:
    render_header(snapshot, cache_age)
    print("---")
    print(f"Colima: {'running' if snapshot.get('colima_running') else 'stopped'} | color={COLOR_OK if snapshot.get('colima_running') else COLOR_OFF}")
    print(f"Current context: {snapshot.get('context') or 'none'}")
    print(f"Expected context: {snapshot.get('expected_context')}")
    if snapshot.get("context") and snapshot.get("context") != snapshot.get("expected_context"):
        print(f"Context drift: yes | color={COLOR_WARN}")
    print(f"kind cluster exists: {bool_label(bool(snapshot.get('kind_cluster_exists')))}")
    print(f"Reachable: {bool_label(bool(snapshot.get('cluster_reachable')))}")

    if cache_age is not None:
        print(f"Snapshot age: {relative_age(snapshot.get('captured_at'))} (cached {int(cache_age)}s)")
    else:
        print(f"Snapshot age: {relative_age(snapshot.get('captured_at'))}")

    if snapshot.get("cluster_reachable"):
        print(f"Nodes ready: {snapshot.get('ready_nodes', 0)}/{snapshot.get('node_count', 0)}")
        phases = snapshot.get("pod_phases") or {}
        print(
            "Pods: "
            f"{phases.get('Running', 0)} running, "
            f"{phases.get('Pending', 0)} pending, "
            f"{phases.get('Failed', 0)} failed, "
            f"{phases.get('Succeeded', 0)} succeeded"
        )
        print(f"Problem pods: {snapshot.get('problem_pod_count', 0)}")
    elif snapshot.get("kubectl_error"):
        error_line = str(snapshot["kubectl_error"]).replace("\n", " ")
        print(f"kubectl: {error_line[:180]}")

    print_refresh()

    print_section("Health")
    problems = snapshot.get("problem_pods") or []
    if not problems:
        if snapshot.get("cluster_reachable"):
            print(f"No unhealthy pods | color={COLOR_OK}")
        else:
            print(f"Cluster not reachable | color={COLOR_BAD}")
    else:
        for item in problems[:8]:
            print(
                f"-- {item['namespace']}/{item['name']} — {item['reason']} "
                f"(restarts {item['restarts']}) | color={COLOR_BAD}"
            )
            logs_cmd = shell_join(
                [
                    KUBECTL_BIN,
                    "--context",
                    DEFAULT_CONTEXT,
                    "logs",
                    "-n",
                    item["namespace"],
                    item["name"],
                    "--all-containers",
                    "--tail",
                    "100",
                ]
            )
            describe_cmd = shell_join(
                [KUBECTL_BIN, "--context", DEFAULT_CONTEXT, "describe", "pod", "-n", item["namespace"], item["name"]]
            )
            print(f"---- Logs | {open_in_terminal(logs_cmd)}")
            print(f"---- Describe | {open_in_terminal(describe_cmd)}")

    commands = action_commands()
    print_section("Actions")
    if snapshot.get("colima_running"):
        print(f"-- Stop Colima | {shell_action(commands['stop_colima'])}")
    else:
        print(f"-- Start Colima | {shell_action(commands['start_colima'])}")

    if snapshot.get("kind_cluster_exists"):
        print(f"-- Delete kind cluster | {open_in_terminal(commands['delete_kind'])}")
    else:
        print(f"-- Create kind cluster | {open_in_terminal(commands['create_kind'])}")

    if snapshot.get("context") != DEFAULT_CONTEXT:
        print(f"-- Switch to {DEFAULT_CONTEXT} | {shell_action(commands['use_context'])}")

    print(f"-- kubectl get nodes | {open_in_terminal(commands['get_nodes'])}")
    print(f"-- kubectl get pods -A | {open_in_terminal(commands['get_pods'])}")
    print(f"-- kubectl get events -A | {open_in_terminal(commands['get_events'])}")
    print(f"-- kubectl cluster-info | {open_in_terminal(commands['cluster_info'])}")
    print(f"-- docker ps | {open_in_terminal(commands['docker_ps'])}")

    if os.path.exists(K9S_BIN):
        print(f"-- Open k9s | {open_in_terminal(commands['k9s'])}")

    print_section("Open")
    print(f"-- Open kubeconfig | {open_path(Path('~/.kube/config').expanduser())}")
    if GUIDE_PATH.exists():
        print(f"-- Open local guide | {open_path(GUIDE_PATH)}")


def main() -> int:
    snapshot = cluster_snapshot()
    if snapshot.get("cluster_reachable"):
        save_cache(snapshot)
        render(snapshot)
        return 0

    cache = load_cache()
    cached_snapshot = cache.get("snapshot") if isinstance(cache.get("snapshot"), dict) else None
    saved_at = cache.get("saved_at")
    if (
        cached_snapshot
        and isinstance(saved_at, (int, float))
        and snapshot.get("colima_running")
        and snapshot.get("kind_cluster_exists")
    ):
        cache_age = max(time.time() - float(saved_at), 0.0)
        merged_snapshot = {
            **cached_snapshot,
            "colima_running": snapshot.get("colima_running"),
            "colima_detail": snapshot.get("colima_detail"),
            "context": snapshot.get("context"),
            "expected_context": snapshot.get("expected_context"),
            "kind_cluster_exists": snapshot.get("kind_cluster_exists"),
            "kind_clusters": snapshot.get("kind_clusters"),
            "kubectl_error": snapshot.get("kubectl_error"),
        }
        render(merged_snapshot, cache_age)
        return 0

    render(snapshot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
