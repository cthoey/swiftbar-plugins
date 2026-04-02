#!/usr/bin/env python3
# <xbar.title>Continuum monitor</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>choey</xbar.author>
# <xbar.desc>Shows Continuum autonomous worker status, recent activity, and quick actions.</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.refreshOnOpen>false</swiftbar.refreshOnOpen>

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:
    tomllib = None

DEFAULT_RUNNER_ROOT = str(Path("~/continuum-runner").expanduser())
CONFIG_PATH_DEFAULT = Path(
    os.environ.get(
        "CONTINUUM_CONFIG",
        os.path.expanduser("~/.config/continuum/config.toml"),
    )
)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

COLOR_RUNNING = "#2a9d8f"
COLOR_DONE = "#2a9d8f"
COLOR_BLOCKED = "#d7263d"
COLOR_FAILED = "#d7263d"
COLOR_WAIT = "#ffb703"
COLOR_IDLE = "#6c757d"
COLOR_UNKNOWN = "#7b2cbf"
COLOR_STALE = "#ff7f11"


def read_toml(path: Path) -> dict[str, Any]:
    if tomllib is None:
        return read_simple_toml(path)
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_simple_toml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    data: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            data[key] = value[1:-1]
        elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
            data[key] = value[1:-1]
        elif value.lower() in {"true", "false"}:
            data[key] = value.lower() == "true"
        else:
            data[key] = value
    return data


def resolve_runner_root() -> tuple[Path, Path | None]:
    user_config_path = CONFIG_PATH_DEFAULT.expanduser()
    user_config = read_toml(user_config_path) if user_config_path.exists() else {}
    configured_runner_root = user_config.get("runner_root")

    runner_root = (
        os.environ.get("CONTINUUM_RUNNER_ROOT")
        or (configured_runner_root if isinstance(configured_runner_root, str) else None)
        or os.environ.get("RELAY_RUNNER_ROOT")
        or os.environ.get("CODEX_RUNNER_ROOT")
        or DEFAULT_RUNNER_ROOT
    )
    return Path(runner_root).expanduser(), (
        user_config_path if user_config_path.exists() else None
    )


RUNNER_ROOT, USER_CONFIG_PATH = resolve_runner_root()
CONFIG_PATH = RUNNER_ROOT / "projects.json"
RUNTIME_ROOT = RUNNER_ROOT / "runtime"


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def shell_action(command: str, terminal: bool = False, refresh: bool = True) -> str:
    return (
        f"bash={shell_quote('/bin/zsh')} "
        f"param0={shell_quote('-lc')} "
        f"param1={shell_quote(command)} "
        f"terminal={'true' if terminal else 'false'} "
        f"refresh={'true' if refresh else 'false'}"
    )


def open_in_terminal(command: str) -> str:
    script = f'tell application "Terminal" to do script {json.dumps(command)}'
    return (
        f"bash={shell_quote('/usr/bin/osascript')} "
        f"param0={shell_quote('-e')} "
        f"param1={shell_quote(script)} "
        "terminal=false refresh=false"
    )


def open_path(path: Path) -> str:
    return (
        f"bash={shell_quote('/usr/bin/open')} "
        f"param0={shell_quote(str(path))} "
        "terminal=false refresh=false"
    )


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def load_projects() -> list[dict[str, Any]]:
    raw = read_json(CONFIG_PATH)
    if not raw:
        return []
    projects = raw.get("projects") or []
    if not isinstance(projects, list):
        return []
    return [item for item in projects if isinstance(item, dict)]


def load_status(project_name: str) -> dict[str, Any] | None:
    return read_json(RUNTIME_ROOT / project_name / "state" / "status.json")


def load_restart_state(project_name: str) -> dict[str, Any] | None:
    return read_json(RUNNER_ROOT / f"restart.{project_name}.json")


def iso_to_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except Exception:
        return None


def relative_age(value: dt.datetime | None) -> str:
    if value is None:
        return "unknown"
    now = dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    delta = now - value.astimezone(dt.timezone.utc)
    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def duration_since(value: dt.datetime | None) -> str:
    if value is None:
        return "unknown"
    now = dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    delta = now - value.astimezone(dt.timezone.utc)
    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = 0
    minutes, secs = divmod(seconds, 60)
    hours, mins = divmod(minutes, 60)
    days, hrs = divmod(hours, 24)
    if days:
        return f"{days}d {hrs}h"
    if hours:
        return f"{hours}h {mins}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_local_time(value: dt.datetime | None) -> str:
    if value is None:
        return "unknown"
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def format_time_with_age(value: dt.datetime | None) -> str:
    if value is None:
        return "unknown"
    return f"{format_local_time(value)} ({relative_age(value)})"


def file_mtime(path: Path) -> dt.datetime | None:
    if not path.exists():
        return None
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    except Exception:
        return None


def file_age(path: Path) -> str:
    ts = file_mtime(path)
    if ts is None:
        return "missing" if not path.exists() else "unknown"
    return relative_age(ts)


def file_is_fresh(path: Path, threshold_seconds: int) -> bool:
    if not path.exists():
        return False
    try:
        age = dt.datetime.now(dt.timezone.utc).timestamp() - path.stat().st_mtime
    except Exception:
        return False
    return age <= threshold_seconds


def tail_lines(path: Path, max_lines: int = 6, max_bytes: int = 16384) -> list[str]:
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            start = max(size - max_bytes, 0)
            f.seek(start)
            data = f.read()
    except Exception:
        return []
    if start > 0:
        newline = data.find(b"\n")
        if newline != -1:
            data = data[newline + 1 :]
    text = data.decode("utf-8", errors="replace")
    lines = [strip_ansi(line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    filtered: list[str] = []
    for line in reversed(lines):
        if line.startswith("model:") or line.startswith("provider:") or line.startswith("approval:"):
            continue
        if line.startswith("sandbox:") or line.startswith("reasoning effort:"):
            continue
        if line.startswith("reasoning summaries:") or line.startswith("session id:"):
            continue
        filtered.append(line)
        if len(filtered) >= max_lines:
            break
    filtered.reverse()
    return filtered


def status_color(status: str, log_path: Path) -> str:
    normalized = (status or "").upper()
    if normalized == "RUNNING":
        return COLOR_RUNNING if file_is_fresh(log_path, 120) else COLOR_STALE
    if normalized == "DONE":
        return COLOR_DONE
    if normalized == "BLOCKED":
        return COLOR_BLOCKED
    if normalized == "FAILED":
        return COLOR_FAILED
    if normalized == "RATE_LIMIT_WAIT":
        return COLOR_WAIT
    if normalized in {"", "IDLE"}:
        return COLOR_IDLE
    return COLOR_UNKNOWN


def short_status(status: str, log_path: Path) -> str:
    normalized = (status or "").upper()
    if normalized == "RUNNING":
        return "RUN" if file_is_fresh(log_path, 120) else "STALE"
    if normalized == "DONE":
        return "DONE"
    if normalized == "BLOCKED":
        return "BLOCK"
    if normalized == "FAILED":
        return "FAIL"
    if normalized == "RATE_LIMIT_WAIT":
        return "WAIT"
    if normalized in {"", "IDLE"}:
        return "IDLE"
    return normalized[:8]


def render_header(project_rows: list[dict[str, Any]]) -> None:
    if not project_rows:
        print(f"Continuum 0 running | color={COLOR_IDLE}")
        return

    total = len(project_rows)
    running = sum(1 for row in project_rows if row["short_status"] == "RUN")
    blocked = sum(1 for row in project_rows if row["status"] == "BLOCKED")
    failed = sum(1 for row in project_rows if row["status"] == "FAILED")
    waiting = sum(1 for row in project_rows if row["status"] == "RATE_LIMIT_WAIT")
    stale = sum(1 for row in project_rows if row["short_status"] == "STALE")
    done = sum(1 for row in project_rows if row["status"] == "DONE")
    restarting = sum(
        1
        for row in project_rows
        if row["restart_phase"] in {"requested", "waiting", "relaunching"}
    )

    title = f"Continuum {running}/{total} running"
    extras: list[str] = []
    if restarting:
        noun = "restart" if restarting == 1 else "restarts"
        extras.append(f"{restarting} {noun} pending")
    if stale:
        extras.append(f"{stale} stale")
    if waiting:
        extras.append(f"{waiting} waiting")
    if blocked:
        extras.append(f"{blocked} blocked")
    if failed:
        extras.append(f"{failed} failed")
    if done and not (running or stale or waiting or blocked or failed):
        extras.append(f"{done} done")
    if extras:
        title = f"{title}, {', '.join(extras[:2])}"

    color = COLOR_IDLE
    if blocked or failed:
        color = COLOR_BLOCKED
    elif waiting or stale:
        color = COLOR_WAIT
    elif running:
        color = COLOR_RUNNING
    elif done:
        color = COLOR_DONE

    print(f"{title} | color={color}")


def main() -> int:
    projects = load_projects()
    rows: list[dict[str, Any]] = []
    for project in projects:
        name = str(project.get("name") or "unknown")
        project_path = Path(str(project.get("path") or "."))
        status_path = RUNTIME_ROOT / name / "state" / "status.json"
        log_path = RUNTIME_ROOT / name / "logs" / "codex.log"
        supervisor_log = RUNNER_ROOT / f"supervisor.{name}.out.log"
        supervisor_pidfile = RUNNER_ROOT / f"supervisor.{name}.pid"
        restart_state_path = RUNNER_ROOT / f"restart.{name}.json"
        progress_log_path = project_path / "docs" / "codex-progress.md"
        status = load_status(name) or {}
        restart_state = load_restart_state(name) or {}
        last_status = str(status.get("last_status") or ("IDLE" if not status else "UNKNOWN")).upper()
        updated_at = str(status.get("updated_at") or "")
        updated_dt = iso_to_datetime(updated_at)
        log_dt = file_mtime(log_path)
        progress_dt = file_mtime(progress_log_path)
        supervisor_started_dt = file_mtime(supervisor_pidfile)
        restart_requested_dt = iso_to_datetime(str(restart_state.get("requested_at") or ""))
        rows.append(
            {
                "name": name,
                "path": project_path,
                "status_path": status_path,
                "log_path": log_path,
                "supervisor_log": supervisor_log,
                "supervisor_pidfile": supervisor_pidfile,
                "restart_state_path": restart_state_path,
                "progress_log_path": progress_log_path,
                "status": last_status,
                "short_status": short_status(last_status, log_path),
                "color": status_color(last_status, log_path),
                "phase": str(status.get("phase") or project.get("phase") or "idle"),
                "pass_num": status.get("pass_num"),
                "profile": str(status.get("profile") or project.get("profile") or ""),
                "updated_at": updated_at,
                "updated_dt": updated_dt,
                "log_dt": log_dt,
                "progress_dt": progress_dt,
                "supervisor_started_dt": supervisor_started_dt,
                "restart_phase": str(restart_state.get("phase") or ""),
                "restart_detail": str(restart_state.get("detail") or ""),
                "restart_requested_dt": restart_requested_dt,
                "status_detail": str(status.get("status_detail") or ""),
                "log_age": file_age(log_path),
            }
        )

    render_header(rows)
    print("---")

    if not CONFIG_PATH.exists():
        print(f"Missing config: {CONFIG_PATH}")
        print(f"Open runner folder | {open_path(RUNNER_ROOT)}")
        print("Refresh | refresh=true")
        return 0

    print(f"Runner: {RUNNER_ROOT.name}")
    print(f"Config: {CONFIG_PATH.name}")
    if USER_CONFIG_PATH is not None:
        print(f"Home config: {USER_CONFIG_PATH}")
    print("---")

    for row in rows:
        title = (
            f"{row['name']}: {row['short_status']}"
            f" | color={row['color']}"
            f" ansi=false"
        )
        print(title)

        if row["pass_num"] is not None:
            print(f"--Pass: {row['pass_num']} ({row['phase']})")
        else:
            print("--Pass: not started")

        print(f"--Profile: {row['profile'] or 'default'}")
        if row["supervisor_started_dt"] is not None:
            print(f"--Supervisor started: {format_time_with_age(row['supervisor_started_dt'])}")
            print(f"--Supervisor age: {duration_since(row['supervisor_started_dt'])}")
        else:
            print("--Supervisor started: unknown")

        if row["status"] in {"RUNNING", "RATE_LIMIT_WAIT"}:
            print(f"--Current pass started: {format_time_with_age(row['updated_dt'])}")
            print(f"--Current pass age: {duration_since(row['updated_dt'])}")
        elif row["updated_dt"] is not None:
            print(f"--Last state change: {format_time_with_age(row['updated_dt'])}")
        else:
            print("--Last state change: unknown")

        if row["log_dt"] is not None:
            print(f"--Last worker activity: {format_time_with_age(row['log_dt'])}")
        else:
            print("--Last worker activity: missing")

        if row["progress_dt"] is not None:
            print(f"--Last progress checkpoint: {format_time_with_age(row['progress_dt'])}")

        if row["restart_phase"]:
            if row["restart_phase"] in {"requested", "waiting"}:
                print(f"--Restart pending since: {format_time_with_age(row['restart_requested_dt'])}")
            elif row["restart_phase"] == "relaunching":
                print("--Restart status: relaunching")
            elif row["restart_phase"] == "timed_out":
                print("--Restart status: timed out")
            elif row["restart_phase"] == "failed":
                print("--Restart status: relaunch failed")

            if row["restart_detail"]:
                print(f"--Restart detail: {row['restart_detail']}")

        if row["status_detail"]:
            detail = row["status_detail"].replace("\n", " ")
            print(f"--Detail: {detail}")

        recent = tail_lines(row["log_path"])
        if recent:
            print("--Recent log")
            for line in recent:
                compact = line.replace("|", "/")
                print(f"----{compact}")

        runner_cd = shell_quote(str(RUNNER_ROOT))
        project_name = shell_quote(str(row["name"]))
        tail_log_cmd = f"tail -f {shell_quote(str(row['log_path']))}"
        tail_supervisor_cmd = f"tail -f {shell_quote(str(row['supervisor_log']))}"
        print("--Actions")
        print(
            f"----Start project | "
            f"{shell_action(f'cd {runner_cd} && ./launch_project.sh {project_name}', terminal=False, refresh=True)}"
        )
        print(
            f"----Restart project | "
            f"{shell_action(f'cd {runner_cd} && ./restart_project.sh {project_name}', terminal=False, refresh=True)}"
        )
        print(
            f"----Stop after pass | "
            f"{shell_action(f'cd {runner_cd} && ./stop_project.sh {project_name}', terminal=False, refresh=True)}"
        )
        print(
            f"----Stop now | "
            f"{shell_action(f'cd {runner_cd} && ./stop_now_project.sh {project_name}', terminal=False, refresh=True)}"
        )
        print(
            f"----Tail codex.log | "
            f"{open_in_terminal(tail_log_cmd)}"
        )
        print(
            f"----Tail supervisor log | "
            f"{open_in_terminal(tail_supervisor_cmd)}"
        )
        print(f"----Open project folder | {open_path(row['path'])}")
        print(f"----Open runner folder | {open_path(RUNNER_ROOT)}")
        if row["status_path"].exists():
            print(f"----Open status.json | {open_path(row['status_path'])}")
        if row["log_path"].exists():
            print(f"----Open codex.log | {open_path(row['log_path'])}")
        if row["restart_state_path"].exists():
            print(f"----Open restart state | {open_path(row['restart_state_path'])}")
        if row["progress_log_path"].exists():
            print(f"----Open codex-progress.md | {open_path(row['progress_log_path'])}")

        print("---")

    print("Refresh Now | refresh=true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
