#!/usr/bin/env python3
# <xbar.title>Codex runner monitor</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>OpenAI</xbar.author>
# <xbar.desc>Shows Codex autonomous runner status, recent activity, and quick actions.</xbar.desc>
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

RUNNER_ROOT = Path(
    os.environ.get(
        "CODEX_RUNNER_ROOT",
        "/Users/choey/Documents/10-projects/shared-tools/codex-runner",
    )
)
CONFIG_PATH = RUNNER_ROOT / "projects.json"
RUNTIME_ROOT = RUNNER_ROOT / "runtime"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

COLOR_RUNNING = "#2a9d8f"
COLOR_DONE = "#2a9d8f"
COLOR_BLOCKED = "#d7263d"
COLOR_FAILED = "#d7263d"
COLOR_WAIT = "#ffb703"
COLOR_IDLE = "#6c757d"
COLOR_UNKNOWN = "#7b2cbf"
COLOR_STALE = "#ff7f11"


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


def file_age(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        ts = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    except Exception:
        return "unknown"
    return relative_age(ts)


def file_is_fresh(path: Path, threshold_seconds: int) -> bool:
    if not path.exists():
        return False
    try:
        age = dt.datetime.now(dt.timezone.utc).timestamp() - path.stat().st_mtime
    except Exception:
        return False
    return age <= threshold_seconds


def tail_lines(path: Path, max_lines: int = 6) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
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
        print(f"Codex 0 | color={COLOR_IDLE}")
        return

    running = sum(1 for row in project_rows if row["status"] == "RUNNING")
    blocked = sum(1 for row in project_rows if row["status"] == "BLOCKED")
    failed = sum(1 for row in project_rows if row["status"] == "FAILED")
    waiting = sum(1 for row in project_rows if row["status"] == "RATE_LIMIT_WAIT")
    stale = sum(1 for row in project_rows if row["short_status"] == "STALE")
    done = sum(1 for row in project_rows if row["status"] == "DONE")

    pieces: list[str] = ["Codex"]
    if running:
        pieces.append(f"R{running}")
    if stale:
        pieces.append(f"S{stale}")
    if waiting:
        pieces.append(f"W{waiting}")
    if blocked:
        pieces.append(f"B{blocked}")
    if failed:
        pieces.append(f"F{failed}")
    if done and not (running or stale or waiting or blocked or failed):
        pieces.append(f"D{done}")

    color = COLOR_IDLE
    if blocked or failed:
        color = COLOR_BLOCKED
    elif waiting or stale:
        color = COLOR_WAIT
    elif running:
        color = COLOR_RUNNING
    elif done:
        color = COLOR_DONE

    print(f"{' '.join(pieces)} | color={color}")


def main() -> int:
    projects = load_projects()
    rows: list[dict[str, Any]] = []
    for project in projects:
        name = str(project.get("name") or "unknown")
        project_path = Path(str(project.get("path") or "."))
        status_path = RUNTIME_ROOT / name / "state" / "status.json"
        log_path = RUNTIME_ROOT / name / "logs" / "codex.log"
        supervisor_log = RUNNER_ROOT / f"supervisor.{name}.out.log"
        status = load_status(name) or {}
        last_status = str(status.get("last_status") or ("IDLE" if not status else "UNKNOWN")).upper()
        rows.append(
            {
                "name": name,
                "path": project_path,
                "status_path": status_path,
                "log_path": log_path,
                "supervisor_log": supervisor_log,
                "status": last_status,
                "short_status": short_status(last_status, log_path),
                "color": status_color(last_status, log_path),
                "phase": str(status.get("phase") or project.get("phase") or "idle"),
                "pass_num": status.get("pass_num"),
                "profile": str(status.get("profile") or project.get("profile") or ""),
                "updated_at": str(status.get("updated_at") or ""),
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
        print(f"--State updated: {relative_age(iso_to_datetime(row['updated_at']))}")
        print(f"--Log activity: {row['log_age']}")

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
            f"----Stop project | "
            f"{shell_action(f'cd {runner_cd} && ./stop_project.sh {project_name}', terminal=False, refresh=True)}"
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

        print("---")

    print("Refresh Now | refresh=true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
