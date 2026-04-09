#!/usr/bin/env python3
# <xbar.title>LeadOps</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.author>Chris Hoey</xbar.author>
# <xbar.desc>LeadOps daily brief monitor with quick actions for running curation, opening packets, and copying outreach drafts.</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.refreshOnOpen>false</swiftbar.refreshOnOpen>

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
from typing import Any

COLOR_GOOD = "#2a9d8f"
COLOR_WARN = "#ff7f11"
COLOR_BAD = "#d7263d"
COLOR_IDLE = "#6c757d"
COLOR_INFO = "#457b9d"

PLUGIN_DIR = Path(__file__).resolve().parent
PLUGIN_REPO_ROOT = PLUGIN_DIR.parent
SIBLING_LEADOPS_ROOT = PLUGIN_REPO_ROOT.parent / "leadops"
DEFAULT_WORKSPACE = Path(
    os.environ.get(
        "LEADOPS_WORKSPACE",
        "~/Library/Application Support/LeadOps/default",
    )
).expanduser()
DEFAULT_LAUNCHD_LABEL = os.environ.get("LEADOPS_LAUNCHD_LABEL", "dev.leadops.daily")


def _first_existing(*candidates: object) -> str:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate)).expanduser()
        if path.exists():
            return str(path)
    return ""


def shell_quote(value: str) -> str:
    return shlex.quote(value)


LEADOPS_BIN = os.environ.get("LEADOPS_BIN") or _first_existing(
    shutil.which("leadops"),
    SIBLING_LEADOPS_ROOT / "bin" / "leadops",
)
LEADOPS_DAILY_BIN = os.environ.get("LEADOPS_DAILY_BIN") or _first_existing(
    shutil.which("leadops-daily"),
    SIBLING_LEADOPS_ROOT / "bin" / "leadops-daily",
)
LEADOPS_SWIFTBAR_BIN = os.environ.get("LEADOPS_SWIFTBAR_BIN") or _first_existing(
    SIBLING_LEADOPS_ROOT / "bin" / "leadops-swiftbar",
)

def shell_action(command: str, *, terminal: bool = False, refresh: bool = True) -> dict[str, str]:
    return {
        "bash": "/bin/zsh",
        "param0": "-lc",
        "param1": command,
        "terminal": "true" if terminal else "false",
        "refresh": "true" if refresh else "false",
    }


def open_path(path: Path) -> dict[str, str]:
    return {
        "bash": "/usr/bin/open",
        "param0": str(path),
        "terminal": "false",
        "refresh": "false",
    }


def exec_action(program: str, *params: str, refresh: bool = False) -> dict[str, str]:
    payload: dict[str, str] = {
        "bash": program,
        "terminal": "false",
        "refresh": "true" if refresh else "false",
    }
    for index, param in enumerate(params):
        payload[f"param{index}"] = param
    return payload


def copy_text_action(text: str) -> dict[str, str]:
    return shell_action(f"printf %s {shell_quote(text)} | pbcopy", terminal=False, refresh=False)


def render_line(text: str, **attrs: str | bool | int | float) -> str:
    if not attrs:
        return text
    parts = [text]
    for key, value in attrs.items():
        if isinstance(value, bool):
            encoded = "true" if value else "false"
        else:
            encoded = str(value)
        parts.append(f"{key}={shell_quote(encoded)}")
    return " | ".join([parts[0], " ".join(parts[1:])])


def iso_date_or_none(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value)
    except Exception:
        return None


def iso_datetime_or_none(value: str) -> dt.datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(normalized)
    except Exception:
        return None


def iso_date_plus(days: int, *, base: dt.date | None = None) -> str:
    anchor = base or dt.date.today()
    return (anchor + dt.timedelta(days=days)).isoformat()


def latest_packet_dir(outbox_dir: Path) -> Path | None:
    packet_dirs: list[tuple[dt.date, Path]] = []
    if not outbox_dir.exists():
        return None
    for child in outbox_dir.iterdir():
        if not child.is_dir():
            continue
        parsed = iso_date_or_none(child.name)
        if parsed is not None:
            packet_dirs.append((parsed, child))
    if not packet_dirs:
        return None
    packet_dirs.sort(key=lambda item: item[0], reverse=True)
    return packet_dirs[0][1]


def load_latest_packet(workspace: Path) -> tuple[dict[str, Any] | None, Path | None]:
    packet_dir = latest_packet_dir(workspace / "outbox")
    if packet_dir is None:
        return None, None
    json_path = packet_dir / "daily-brief.json"
    if not json_path.exists():
        return None, packet_dir
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None, packet_dir
    if not isinstance(payload, dict):
        return None, packet_dir
    return payload, packet_dir


def latest_logs(workspace: Path) -> tuple[Path, Path]:
    logs_dir = workspace / "var" / "log"
    return logs_dir / "launchd.stdout.log", logs_dir / "launchd.stderr.log"


def load_run_state(workspace: Path) -> dict[str, str] | None:
    path = workspace / "var" / "run-state.env"
    if not path.exists():
        return None

    payload: dict[str, str] = {}
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in raw_line:
                continue
            key, value = raw_line.split("=", 1)
            payload[key.strip()] = value.strip()
    except Exception:
        return None

    pid_text = payload.get("pid", "")
    if not pid_text.isdigit():
        return None

    try:
        os.kill(int(pid_text), 0)
    except OSError:
        return None

    return payload


def read_launchd_schedule(label: str) -> str | None:
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not plist_path.exists():
        return None
    try:
        with plist_path.open("rb") as fh:
            payload = plistlib.load(fh)
    except Exception:
        return None
    interval = payload.get("StartCalendarInterval")
    if not isinstance(interval, dict):
        return None
    hour = interval.get("Hour")
    minute = interval.get("Minute")
    if not isinstance(hour, int) or not isinstance(minute, int):
        return None
    return f"{hour:02d}:{minute:02d}"


def mark_status_command(
    workspace: Path,
    *,
    target_id: int,
    status: str,
    reason: str,
    followup_date: str | None = None,
) -> dict[str, str]:
    if not LEADOPS_SWIFTBAR_BIN:
        return shell_action("echo 'LeadOps SwiftBar helper not found.'; exit 1", terminal=False, refresh=False)
    params = [
        "mark-status",
        str(workspace),
        str(target_id),
        status,
        "--reason",
        reason,
    ]
    if followup_date:
        params.extend(["--followup-date", followup_date])
    return exec_action(LEADOPS_SWIFTBAR_BIN, *params, refresh=True)


def copy_full_draft_command(text: str) -> str:
    return f"printf %s {shell_quote(text)} | pbcopy"


def topbar_text(packet: dict[str, Any] | None, workspace: Path) -> tuple[str, str]:
    if not workspace.exists():
        return "LeadOps --", COLOR_BAD
    run_state = load_run_state(workspace)
    if packet is None:
        if run_state:
            return f"LeadOps {spinner_frame()} 0 new · 0 due", COLOR_WARN
        return "LeadOps 0 new · 0 due", COLOR_IDLE
    packet_date = iso_date_or_none(str(packet.get("packet_date", "")))
    new_targets = packet.get("new_targets", [])
    followups = packet.get("followups_due", [])
    new_count = len(new_targets) if isinstance(new_targets, list) else 0
    followup_count = len(followups) if isinstance(followups, list) else 0
    label = f"LeadOps {new_count} new \u00b7 {followup_count} due"
    if run_state:
        return f"LeadOps {spinner_frame()} {new_count} new \u00b7 {followup_count} due", COLOR_WARN
    if packet_date is None:
        return label, COLOR_WARN
    today = dt.date.today()
    if packet_date < today:
        return label, COLOR_WARN
    if new_count or followup_count:
        return label, COLOR_GOOD
    return label, COLOR_IDLE


def spinner_frame() -> str:
    frames = ("◐", "◓", "◑", "◒")
    return frames[int(dt.datetime.now().timestamp() // 15) % len(frames)]


def human_age_text(started_at: dt.datetime | None) -> str:
    if started_at is None:
        return "unknown"
    now = dt.datetime.now(dt.timezone.utc)
    delta = now - started_at.astimezone(dt.timezone.utc)
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return f"{seconds}s ago"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours, rem_minutes = divmod(minutes, 60)
    return f"{hours}h {rem_minutes}m ago"


def render_target_section(title: str, items: list[dict[str, Any]], *, workspace: Path, packet_date: str) -> None:
    print(title)
    if not items:
        print("--None today.")
        return

    for item in items:
        target = item.get("target", {})
        assessment = item.get("assessment", {})
        section = str(item.get("section", "") or "")
        target_id = int(target.get("id", 0) or 0)
        name = str(target.get("name", "Unknown target"))
        kind = str(target.get("kind", "-"))
        status = str(target.get("status", "candidate") or "candidate")
        score = assessment.get("fit_score", "-")
        confidence = assessment.get("confidence", "-")
        target_url = str(target.get("url", "") or "")
        print(
            render_line(
                f"--{name} [{kind}] \u2022 {score}",
                color=COLOR_INFO if target_url else COLOR_IDLE,
            )
        )
        why_fit = str(assessment.get("why_fit", "") or "").strip()
        why_now = str(assessment.get("why_now", "") or "").strip()
        subject = str(assessment.get("draft_subject", "") or "").strip()
        body = str(assessment.get("draft_body", "") or "").strip()
        full_draft = f"Subject: {subject}\n\n{body}".strip()
        if why_fit:
            print(render_line(f"----Why fit: {why_fit}", trim=False, ansi=False))
        if why_now:
            print(render_line(f"----Why now: {why_now}", trim=False, ansi=False))
        print(f"----Status: {status}")
        print(f"----Confidence: {confidence}")
        if full_draft:
            print(render_line("----Copy full draft", **shell_action(copy_full_draft_command(full_draft), refresh=False)))
        if target_url:
            print(render_line("----Open target", href=target_url))
        if subject:
            print(render_line("----Copy subject", **copy_text_action(subject)))
        if body:
            print(render_line("----Copy draft body", **copy_text_action(body)))
        if target_id > 0:
            if section == "new_target":
                print(
                    render_line(
                        "----Approve",
                        **mark_status_command(
                            workspace,
                            target_id=target_id,
                            status="approved",
                            reason="Approved from SwiftBar.",
                        ),
                    )
                )
                print(
                    render_line(
                        f"----Snooze 7d ({iso_date_plus(7, base=iso_date_or_none(packet_date))})",
                        **mark_status_command(
                            workspace,
                            target_id=target_id,
                            status=status,
                            followup_date=iso_date_plus(7, base=iso_date_or_none(packet_date)),
                            reason="Snoozed from SwiftBar.",
                        ),
                    )
                )
            elif section == "followup":
                print(
                    render_line(
                        "----Mark sent",
                        **mark_status_command(
                            workspace,
                            target_id=target_id,
                            status="sent",
                            followup_date=iso_date_plus(7, base=iso_date_or_none(packet_date)),
                            reason="Sent from SwiftBar.",
                        ),
                    )
                )
                print(
                    render_line(
                        "----Mark replied",
                        **mark_status_command(
                            workspace,
                            target_id=target_id,
                            status="replied",
                            reason="Marked replied from SwiftBar.",
                        ),
                    )
                )
                print(
                    render_line(
                        f"----Snooze 3d ({iso_date_plus(3, base=iso_date_or_none(packet_date))})",
                        **mark_status_command(
                            workspace,
                            target_id=target_id,
                            status="sent",
                            followup_date=iso_date_plus(3, base=iso_date_or_none(packet_date)),
                            reason="Follow-up snoozed from SwiftBar.",
                        ),
                    )
                )


def print_menu() -> None:
    workspace = DEFAULT_WORKSPACE
    packet, packet_dir = load_latest_packet(workspace)
    run_state = load_run_state(workspace)
    header, color = topbar_text(packet, workspace)
    print(render_line(header, color=color))
    print("---")

    if not workspace.exists():
        print(render_line("Workspace missing", color=COLOR_BAD))
        print(str(workspace))
        return

    print(f"Workspace: {workspace}")
    if not LEADOPS_BIN and not LEADOPS_DAILY_BIN:
        print(render_line("LeadOps CLI not found on PATH", color=COLOR_WARN))
    if not LEADOPS_SWIFTBAR_BIN:
        print(render_line("LeadOps SwiftBar helper not found", color=COLOR_WARN))
    schedule = read_launchd_schedule(DEFAULT_LAUNCHD_LABEL)
    if schedule:
        print(f"Scheduled run: {schedule}")
    if run_state:
        started_at = iso_datetime_or_none(run_state.get("started_at", ""))
        pid_text = run_state.get("pid", "?")
        print(render_line(f"Run status: running ({human_age_text(started_at)}, pid {pid_text})", color=COLOR_WARN))
    print("---")

    if run_state:
        print(render_line("Run already in progress", color=COLOR_WARN))
    else:
        if LEADOPS_SWIFTBAR_BIN:
            print(
                render_line(
                    "Run daily now",
                    **exec_action(
                        LEADOPS_SWIFTBAR_BIN,
                        "run-daily",
                        str(workspace),
                        "--discover-track",
                        "connectors",
                        "--discover-track",
                        "founders",
                        "--discover-per-query-limit",
                        "2",
                        "--send-digest",
                        refresh=True,
                    ),
                )
            )
        else:
            print(render_line("Run daily now unavailable", color=COLOR_WARN))
    if packet and packet.get("packet_date"):
        packet_date = str(packet["packet_date"])
        if LEADOPS_SWIFTBAR_BIN:
            print(
                render_line(
                    "Send latest digest",
                    **exec_action(
                        LEADOPS_SWIFTBAR_BIN,
                        "send-digest",
                        str(workspace),
                        packet_date,
                        refresh=True,
                    ),
                )
            )

    print(render_line("Open workspace", **open_path(workspace)))
    print(render_line("Open config", **open_path(workspace / "leadops.toml")))
    stdout_log, stderr_log = latest_logs(workspace)
    if stdout_log.exists():
        print(render_line("Open stdout log", **open_path(stdout_log)))
    if stderr_log.exists():
        print(render_line("Open stderr log", **open_path(stderr_log)))

    if packet is None:
        print("---")
        print(render_line("No packet yet", color=COLOR_IDLE))
        return

    packet_date = str(packet.get("packet_date", "unknown"))
    packet_date_parsed = iso_date_or_none(packet_date)
    stale_note = ""
    if packet_date_parsed is not None and packet_date_parsed < dt.date.today():
        stale_note = " (latest packet is not from today)"
    print("---")
    print(render_line(f"Latest packet: {packet_date}{stale_note}", color=COLOR_WARN if stale_note else COLOR_GOOD))

    if packet_dir is not None:
        brief_md = packet_dir / "daily-brief.md"
        brief_json = packet_dir / "daily-brief.json"
        digest = packet_dir / "daily-digest.txt"
        if brief_md.exists():
            print(render_line("Open markdown brief", **open_path(brief_md)))
        if brief_json.exists():
            print(render_line("Open JSON brief", **open_path(brief_json)))
        if digest.exists():
            print(render_line("Open digest", **open_path(digest)))

    new_targets = packet.get("new_targets", [])
    followups = packet.get("followups_due", [])
    if isinstance(new_targets, list):
        print("---")
        render_target_section("New targets", new_targets, workspace=workspace, packet_date=packet_date)
    if isinstance(followups, list):
        print("---")
        render_target_section("Follow-ups due", followups, workspace=workspace, packet_date=packet_date)

    print("---")
    print(render_line("Refresh", refresh=True))


if __name__ == "__main__":
    try:
        print_menu()
    except Exception as exc:
        print(render_line("LeadOps !", color=COLOR_BAD))
        print("---")
        print(render_line(f"Plugin error: {exc}", color=COLOR_BAD))
