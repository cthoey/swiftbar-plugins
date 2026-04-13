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
import sqlite3
from typing import Any

COLOR_GOOD = "#2a9d8f"
COLOR_WARN = "#ff7f11"
COLOR_BAD = "#d7263d"
COLOR_IDLE = "#6c757d"
COLOR_INFO = "#457b9d"
COLOR_ACTION = "#0d6efd"

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
APPROACHES = (
    ("transition_focus", "Direct Buyers"),
    ("balanced", "Direct + Connectors"),
    ("public_signal_watch", "Fresh Public Asks"),
)
CANDIDATE_SECTIONS = ("pursue_now", "watch", "nurture")
FOLLOWUP_SECTION = "followup_due"
PRIORITY_ORDER = {
    "now": 0,
    "watch": 1,
    "nurture": 2,
    "older": 3,
    "unseen": 4,
}


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
    shutil.which("leadops-swiftbar"),
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


def local_file_mtime(path: Path) -> dt.datetime | None:
    try:
        timestamp = path.stat().st_mtime
    except OSError:
        return None
    return dt.datetime.fromtimestamp(timestamp).astimezone()


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


def queue_items(packet: dict[str, Any] | None, queue_name: str) -> list[dict[str, Any]]:
    if not isinstance(packet, dict):
        return []
    queues = packet.get("queues", {})
    if not isinstance(queues, dict):
        return []
    items = queues.get(queue_name, [])
    if not isinstance(items, list):
        return []
    return items


def live_target_state(workspace: Path, target_ids: list[int]) -> dict[int, tuple[str, str | None]]:
    db_path = workspace / "var" / "leadops.db"
    if not db_path.exists() or not target_ids:
        return {}
    placeholders = ",".join("?" for _ in target_ids)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT id, status, next_followup_at FROM targets WHERE id IN ({placeholders})",
            tuple(target_ids),
        ).fetchall()
    finally:
        conn.close()
    return {int(row[0]): (str(row[1] or ""), str(row[2] or "") or None) for row in rows}


def backlog_candidates(workspace: Path, *, exclude_target_ids: set[int], limit: int = 20) -> list[dict[str, Any]]:
    db_path = workspace / "var" / "leadops.db"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, kind, name, COALESCE(url, '') AS url, source, status, next_followup_at, last_packeted_at
            FROM targets
            WHERE status IN ('candidate', 'approved')
              AND (next_followup_at IS NULL OR next_followup_at <= ?)
            ORDER BY
              CASE WHEN last_packeted_at IS NULL THEN 1 ELSE 0 END ASC,
              last_packeted_at DESC,
              updated_at DESC,
              created_at DESC
            LIMIT ?
            """,
            (dt.date.today().isoformat(), max(1, limit + len(exclude_target_ids))),
        ).fetchall()
    finally:
        conn.close()

    items: list[dict[str, Any]] = []
    for row in rows:
        target_id = int(row["id"])
        if target_id in exclude_target_ids:
            continue
        target = {
            "id": target_id,
            "kind": str(row["kind"]),
            "name": str(row["name"]),
            "url": str(row["url"]),
            "source": str(row["source"]),
            "status": str(row["status"]),
            "next_followup_at": row["next_followup_at"],
            "last_packeted_at": row["last_packeted_at"],
        }
        priority_label = "older" if row["last_packeted_at"] else "unseen"
        assessment = {
            "profile_fit": "backlog",
            "activation_signal": "backlog",
            "evidence_confidence": "backlog",
            "freshness": "backlog",
            "confidence": "-",
            "summary_thesis": "",
            "risk_tags": [],
            "draft_subject": "",
            "draft_body": "",
        }
        items.append(
            {
                "section": "backlog",
                "target": target,
                "assessment": assessment,
                "priority_label": priority_label,
            }
        )
        if len(items) >= limit:
            break
    return items


def filtered_queue_items(packet: dict[str, Any] | None, queue_name: str, *, workspace: Path) -> list[dict[str, Any]]:
    items = queue_items(packet, queue_name)
    target_ids = [
        int(item.get("target", {}).get("id", 0) or 0)
        for item in items
        if int(item.get("target", {}).get("id", 0) or 0) > 0
    ]
    live_state = live_target_state(workspace, target_ids)
    today = dt.date.today().isoformat()
    visible: list[dict[str, Any]] = []
    for item in items:
        target = item.get("target", {})
        target_id = int(target.get("id", 0) or 0)
        current_status, next_followup_at = live_state.get(
            target_id,
            (str(target.get("status", "") or ""), str(target.get("next_followup_at", "") or "") or None),
        )
        if current_status:
            target["status"] = current_status
        target["next_followup_at"] = next_followup_at
        if queue_name in CANDIDATE_SECTIONS:
            if current_status not in {"candidate", "approved"}:
                continue
            if next_followup_at and next_followup_at > today:
                continue
        elif queue_name == FOLLOWUP_SECTION:
            if current_status != "sent":
                continue
            if not next_followup_at or next_followup_at > today:
                continue
        visible.append(item)
    return visible


def needs_review_items(packet: dict[str, Any] | None, *, workspace: Path) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for queue_name, priority_label in (
        ("pursue_now", "now"),
        ("watch", "watch"),
        ("nurture", "nurture"),
    ):
        for item in filtered_queue_items(packet, queue_name, workspace=workspace):
            item["priority_label"] = priority_label
            merged.append(item)

    latest_target_ids = {
        int(item.get("target", {}).get("id", 0) or 0)
        for item in merged
        if int(item.get("target", {}).get("id", 0) or 0) > 0
    }
    merged.extend(backlog_candidates(workspace, exclude_target_ids=latest_target_ids))
    return merged


def latest_logs(workspace: Path) -> tuple[Path, Path]:
    logs_dir = workspace / "var" / "log"
    return logs_dir / "launchd.stdout.log", logs_dir / "launchd.stderr.log"


def manual_run_log(workspace: Path) -> Path:
    return workspace / "var" / "log" / "manual-run.log"


def scheduler_paths(label: str) -> tuple[Path, Path]:
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    paused = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist.paused"
    return plist, paused


def scheduler_state(label: str) -> str:
    plist, paused = scheduler_paths(label)
    if paused.exists():
        return "paused"
    if plist.exists():
        return "configured"
    return "missing"


def current_review_paths(workspace: Path) -> tuple[Path, Path, Path, Path]:
    review_dir = workspace / "review"
    return (
        review_dir / "current-review.md",
        review_dir / "current-review.json",
        review_dir / "current-review.txt",
        review_dir / "current-review.html",
    )


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


def load_last_run_status(workspace: Path) -> dict[str, str] | None:
    path = workspace / "var" / "last-run.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return {str(key): str(value) for key, value in payload.items()}
    return _fallback_last_run_status_from_logs(workspace)


def _fallback_last_run_status_from_logs(workspace: Path) -> dict[str, str] | None:
    path = manual_run_log(workspace)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    summary = _extract_failure_summary(text)
    if not summary:
        return None
    finished_at = local_file_mtime(path)
    return {
        "mode": "run-daily",
        "status": "failed",
        "finished_at": finished_at.isoformat() if finished_at is not None else "",
        "summary": summary,
        "source": str(path),
    }


def _extract_failure_summary(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if "insufficient_quota" in text and "OpenAI API returned HTTP 429" in text:
        return "OpenAI API quota exhausted (HTTP 429 insufficient_quota)."
    for matcher in (
        lambda line: line.startswith("RuntimeError:"),
        lambda line: line.startswith("ValueError:"),
        lambda line: line.startswith("Exception:"),
        lambda line: "failed with exit code" in line,
        lambda line: "OpenAI API returned HTTP" in line,
        lambda line: "insufficient_quota" in line,
    ):
        for line in reversed(lines):
            if matcher(line):
                return compact_text(line, limit=180)
    if "Traceback" in text and lines:
        return compact_text(lines[-1], limit=180)
    return None


def packet_last_updated(packet_dir: Path | None) -> dt.datetime | None:
    if packet_dir is None:
        return None
    for candidate in (
        packet_dir / "daily-brief.json",
        packet_dir / "daily-brief.md",
        packet_dir / "daily-digest.html",
        packet_dir / "daily-digest.txt",
    ):
        if candidate.exists():
            updated_at = local_file_mtime(candidate)
            if updated_at is not None:
                return updated_at
    return None


def read_launchd_times(label: str) -> tuple[tuple[int, int], ...]:
    plist_path, paused_path = scheduler_paths(label)
    if not plist_path.exists():
        plist_path = paused_path
    if not plist_path.exists():
        return ()
    try:
        with plist_path.open("rb") as fh:
            payload = plistlib.load(fh)
    except Exception:
        return ()
    interval = payload.get("StartCalendarInterval")
    intervals = interval if isinstance(interval, list) else [interval]
    parsed: list[tuple[int, int]] = []
    for item in intervals:
        if not isinstance(item, dict):
            continue
        hour = item.get("Hour")
        minute = item.get("Minute")
        if isinstance(hour, int) and isinstance(minute, int):
            parsed.append((hour, minute))
    return tuple(sorted(set(parsed)))


def next_scheduled_run(label: str) -> dt.datetime | None:
    times = read_launchd_times(label)
    if not times:
        return None

    now = dt.datetime.now().astimezone()
    today = now.date()
    candidates = [
        dt.datetime.combine(today, dt.time(hour=hour, minute=minute), tzinfo=now.tzinfo)
        for hour, minute in times
    ]
    future_today = [candidate for candidate in candidates if candidate > now]
    if future_today:
        return min(future_today)
    first_hour, first_minute = times[0]
    tomorrow = today + dt.timedelta(days=1)
    return dt.datetime.combine(tomorrow, dt.time(hour=first_hour, minute=first_minute), tzinfo=now.tzinfo)


def schedule_summary(label: str) -> tuple[str | None, str | None]:
    times = read_launchd_times(label)
    if not times:
        return None, None

    times_text = ", ".join(f"{hour:02d}:{minute:02d}" for hour, minute in times)
    next_run = next_scheduled_run(label)
    if next_run is None:
        return times_text, None

    today = dt.datetime.now().astimezone().date()
    day_label = "today" if next_run.date() == today else "tomorrow"
    next_text = f"{day_label} {next_run.strftime('%H:%M')}"
    return times_text, next_text


def format_stamp(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


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


def copy_draft_action(workspace: Path, packet_date: str, target_id: int) -> dict[str, str]:
    if not LEADOPS_SWIFTBAR_BIN:
        return shell_action("echo 'LeadOps SwiftBar helper not found.'; exit 1", terminal=False, refresh=False)
    return exec_action(
        LEADOPS_SWIFTBAR_BIN,
        "copy-draft",
        str(workspace),
        packet_date,
        str(target_id),
        refresh=False,
    )


def compact_text(text: str, limit: int = 60) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def short_source_label(source: str) -> str:
    source = source.strip()
    if not source:
        return "-"
    if ":" in source:
        return source.split(":")[-1]
    return source


def best_signal_line(assessment: dict[str, Any]) -> str:
    summary_thesis = str(assessment.get("summary_thesis", "") or "").strip()
    activation_rationale = str(assessment.get("activation_rationale", "") or "").strip()
    evidence = assessment.get("evidence", [])
    if summary_thesis:
        return compact_text(summary_thesis, limit=84)
    if activation_rationale:
        return compact_text(activation_rationale, limit=84)
    if isinstance(evidence, list) and evidence:
        return compact_text(str(evidence[0]), limit=84)
    return ""


def run_approach_action(workspace: Path, approach_name: str) -> dict[str, str]:
    if not LEADOPS_SWIFTBAR_BIN:
        return shell_action("echo 'LeadOps SwiftBar helper not found.'; exit 1", terminal=False, refresh=False)
    return exec_action(
        LEADOPS_SWIFTBAR_BIN,
        "run-daily",
        str(workspace),
        "--approach",
        approach_name,
        "--discover-per-query-limit",
        "2",
        refresh=True,
    )


def pause_schedule_action(workspace: Path, label: str) -> dict[str, str]:
    if not LEADOPS_SWIFTBAR_BIN:
        return shell_action("echo 'LeadOps SwiftBar helper not found.'; exit 1", terminal=False, refresh=False)
    return exec_action(
        LEADOPS_SWIFTBAR_BIN,
        "pause-schedule",
        str(workspace),
        label,
        refresh=True,
    )


def resume_schedule_action(workspace: Path, label: str) -> dict[str, str]:
    if not LEADOPS_SWIFTBAR_BIN:
        return shell_action("echo 'LeadOps SwiftBar helper not found.'; exit 1", terminal=False, refresh=False)
    return exec_action(
        LEADOPS_SWIFTBAR_BIN,
        "resume-schedule",
        str(workspace),
        label,
        refresh=True,
    )


def topbar_text(packet: dict[str, Any] | None, workspace: Path, last_run: dict[str, str] | None) -> tuple[str, str]:
    if not workspace.exists():
        return "LeadOps --", COLOR_BAD
    run_state = load_run_state(workspace)
    last_run_failed = bool(last_run and last_run.get("status") == "failed")
    if packet is None:
        if run_state:
            return f"LeadOps {spinner_frame()} 0 review · 0 due", COLOR_WARN
        if last_run_failed:
            return "LeadOps failed · 0 review · 0 due", COLOR_BAD
        return "LeadOps 0 review · 0 due", COLOR_IDLE
    packet_date = iso_date_or_none(str(packet.get("packet_date", "")))
    queued_count = len(needs_review_items(packet, workspace=workspace))
    followup_count = len(filtered_queue_items(packet, FOLLOWUP_SECTION, workspace=workspace))
    label = f"LeadOps {queued_count} review \u00b7 {followup_count} due"
    if run_state:
        return f"LeadOps {spinner_frame()} {queued_count} review \u00b7 {followup_count} due", COLOR_WARN
    if last_run_failed:
        return f"LeadOps failed \u00b7 {queued_count} review \u00b7 {followup_count} due", COLOR_BAD
    if packet_date is None:
        return label, COLOR_WARN
    today = dt.date.today()
    if packet_date < today:
        return label, COLOR_WARN
    if queued_count or followup_count:
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
        priority_label = str(item.get("priority_label", "") or "")
        target_id = int(target.get("id", 0) or 0)
        name = str(target.get("name", "Unknown target"))
        kind = str(target.get("kind", "-"))
        status = str(target.get("status", "candidate") or "candidate")
        source = short_source_label(str(target.get("source", "") or ""))
        confidence = assessment.get("confidence", "-")
        profile_fit = str(assessment.get("profile_fit", "-") or "-")
        activation_signal = str(assessment.get("activation_signal", "-") or "-")
        evidence_confidence = str(assessment.get("evidence_confidence", "-") or "-")
        freshness = str(assessment.get("freshness", "-") or "-")
        target_url = str(target.get("url", "") or "")
        confidence_text = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else str(confidence)
        signal = best_signal_line(assessment)
        risks = assessment.get("risk_tags", [])
        print(f"--{name}")
        meta_parts = [
            f"id {target_id}" if target_id > 0 else "",
            kind,
            status,
            priority_label,
            f"{profile_fit} fit" if profile_fit not in {"-", "backlog"} else "",
            activation_signal if activation_signal not in {"-", "backlog"} else "",
            f"{evidence_confidence} evidence" if evidence_confidence not in {"-", "backlog"} else "",
            freshness if freshness not in {"-", "backlog"} else "",
            f"conf {confidence_text}" if confidence_text else "",
            f"src {source}" if source != "-" else "",
        ]
        print(f"----{' · '.join(part for part in meta_parts if part)}")
        if signal:
            print(f"----Signal: {signal}")
        if isinstance(risks, list) and risks:
            print(render_line(f"----Risk noted ({len(risks)})", color=COLOR_WARN))
        subject = str(assessment.get("draft_subject", "") or "").strip()
        body = str(assessment.get("draft_body", "") or "").strip()
        full_draft = f"Subject: {subject}\n\n{body}".strip()
        if (subject or body) and full_draft and target_id > 0:
            print(render_line("----Copy full draft", **copy_draft_action(workspace, packet_date, target_id)))
        if target_url:
            print(render_line("----Open target", href=target_url))
        if target_id > 0:
            if section in CANDIDATE_SECTIONS or section == "backlog":
                print(
                    render_line(
                        f"----Hold 30d ({iso_date_plus(30, base=iso_date_or_none(packet_date))})",
                        **mark_status_command(
                            workspace,
                            target_id=target_id,
                            status="candidate",
                            followup_date=iso_date_plus(30, base=iso_date_or_none(packet_date)),
                            reason="Held from SwiftBar for later review.",
                        ),
                    )
                )
                print(
                    render_line(
                        "----Expire",
                        **mark_status_command(
                            workspace,
                            target_id=target_id,
                            status="expired",
                            reason="Expired from SwiftBar.",
                        ),
                    )
                )
                print(
                    render_line(
                        "----Reject",
                        **mark_status_command(
                            workspace,
                            target_id=target_id,
                            status="rejected",
                            reason="Rejected from SwiftBar.",
                        ),
                    )
                )
            elif section == FOLLOWUP_SECTION:
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
    last_run = load_last_run_status(workspace)
    last_updated = packet_last_updated(packet_dir)
    header, header_color = topbar_text(packet, workspace, last_run)
    print(render_line(header, color=header_color))
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
    last_updated_text = format_stamp(last_updated)
    if last_updated_text:
        print(f"Last run: {last_updated_text}")
    current_scheduler_state = scheduler_state(DEFAULT_LAUNCHD_LABEL)
    schedule_times, next_run_text = schedule_summary(DEFAULT_LAUNCHD_LABEL)
    if current_scheduler_state == "paused":
        print(render_line("Schedule: paused", color=COLOR_WARN))
    elif next_run_text:
        print(f"Next run: {next_run_text}")
    if schedule_times:
        print(f"Schedule: {schedule_times}")
    if run_state:
        started_at = iso_datetime_or_none(run_state.get("started_at", ""))
        pid_text = run_state.get("pid", "?")
        print(render_line(f"Run status: running ({human_age_text(started_at)}, pid {pid_text})", color=COLOR_WARN))
    elif last_run and last_run.get("status") == "failed":
        finished_at = iso_datetime_or_none(last_run.get("finished_at", ""))
        finished_text = human_age_text(finished_at) if finished_at is not None else "recently"
        summary = compact_text(last_run.get("summary", "Run failed."), limit=160)
        print(render_line(f"Last run failed ({finished_text})", color=COLOR_BAD))
        print(render_line(summary, color=COLOR_BAD))
    print("---")

    if run_state:
        print(render_line("Run already in progress", color=COLOR_WARN))
    else:
        if LEADOPS_SWIFTBAR_BIN:
            print(
                render_line(
                    "Run approach",
                    color=COLOR_ACTION,
                )
            )
            for approach_name, label in APPROACHES:
                print(render_line(f"--{label}", **run_approach_action(workspace, approach_name)))
            if current_scheduler_state == "paused":
                print(render_line("Resume scheduled runs", **resume_schedule_action(workspace, DEFAULT_LAUNCHD_LABEL)))
            elif current_scheduler_state == "configured":
                print(render_line("Pause scheduled runs", **pause_schedule_action(workspace, DEFAULT_LAUNCHD_LABEL)))
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
    current_review_md, current_review_json, current_review_text, current_review_html = current_review_paths(workspace)
    if current_review_html.exists():
        print(render_line("Open current review", **open_path(current_review_html)))
    if current_review_json.exists():
        print(render_line("Open current review JSON", **open_path(current_review_json)))
    if current_review_text.exists():
        print(render_line("Open current review text", **open_path(current_review_text)))
    if current_review_md.exists():
        print(render_line("Open current review markdown", **open_path(current_review_md)))
    stdout_log, stderr_log = latest_logs(workspace)
    current_manual_run_log = manual_run_log(workspace)
    if current_manual_run_log.exists():
        print(render_line("Open manual run log", **open_path(current_manual_run_log)))
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
        digest_html = packet_dir / "daily-digest.html"
        if digest_html.exists():
            print(render_line("Open HTML digest", **open_path(digest_html)))
        if digest.exists():
            print(render_line("Open text digest", **open_path(digest)))

    review_items = needs_review_items(packet, workspace=workspace)
    followups = filtered_queue_items(packet, FOLLOWUP_SECTION, workspace=workspace)
    if review_items:
        print("---")
        render_target_section("Needs review", review_items, workspace=workspace, packet_date=packet_date)
    if followups:
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
