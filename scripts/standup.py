"""Standup report formatting."""

from __future__ import annotations

import shlex
import sqlite3
from datetime import datetime, timedelta, timezone

from paths import format_path
from queries import parse_period, sessions_in_period


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _resume_command(cwd: str | None, session_id: str) -> str:
    home = str(__import__("pathlib").Path.home())
    if cwd:
        display = format_path(cwd)
        needs_quote = not display.startswith("~")
        quoted = shlex.quote(display) if needs_quote else display
        return f"cd {quoted} && claude --resume {session_id}"
    return f"claude --resume {session_id}"


def _session_label(row: sqlite3.Row) -> str:
    title = row["title"]
    if title:
        return title
    slug = row["slug"]
    if slug:
        return slug.replace("-", " ")[:80]
    return row["session_id"][:8] + "..."


def format_standup(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    active_within_hours: int = 2,
) -> str:
    period_start = parse_period(since)
    rows = sessions_in_period(conn, period_start)
    now = datetime.now(timezone.utc)
    active_cutoff = now - timedelta(hours=active_within_hours)

    grouped: dict[tuple[str, str | None], dict] = {}
    for row in rows:
        cwd = row["cwd"] or "unknown"
        branch = row["git_branch"] or "(no branch)"
        key = (cwd, branch)
        if key not in grouped:
            grouped[key] = {"completed": [], "in_progress": []}

        ended = _parse_ts(row["ended_at"])
        entry = {
            "label": _session_label(row),
            "session_id": row["session_id"],
            "resume": _resume_command(row["cwd"], row["session_id"]),
            "messages": row["message_count"] or 0,
        }
        if ended and ended >= active_cutoff:
            grouped[key]["in_progress"].append(entry)
        else:
            grouped[key]["completed"].append(entry)

    period_label = since or "24h"
    lines = [
        f"## Work Recap — since {period_label}",
        "",
    ]

    if not grouped:
        lines.append("_No sessions in this period. Run `retroscope reindex` if you expect data._")
        return "\n".join(lines)

    lines.append("### Completed")
    has_completed = False
    for (cwd, branch), bucket in sorted(grouped.items(), key=lambda x: x[0][0]):
        for entry in bucket["completed"]:
            has_completed = True
            lines.append(f"- **{format_path(cwd)}** (`{branch}`): {entry['label']}")
            lines.append(f"  - `{entry['resume']}`")
    if not has_completed:
        lines.append("- _(none)_")

    lines.extend(["", "### In Progress"])
    has_active = False
    for (cwd, branch), bucket in sorted(grouped.items(), key=lambda x: x[0][0]):
        for entry in bucket["in_progress"]:
            has_active = True
            lines.append(f"- **{format_path(cwd)}** (`{branch}`): {entry['label']}")
            lines.append(f"  - `{entry['resume']}`")
    if not has_active:
        lines.append("- _(none)_")

    total = sum(
        len(b["completed"]) + len(b["in_progress"]) for b in grouped.values()
    )
    projects = len(grouped)
    lines.extend(
        [
            "",
            "### Stats",
            f"- {total} sessions across {projects} project groups",
        ]
    )
    return "\n".join(lines)
