"""Workflow tips grounded in official Anthropic Claude Code guidelines."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from guidelines import Guideline, get as get_guideline
from paths import format_path
from queries import _iso, parse_period

SHORT_SESSION_MINUTES = 30
FOCUS_AREAS = frozenset({"prompting", "skills", "sessions", "planning"})


@dataclass
class Tip:
    category: str
    severity: str  # high | medium | low
    message: str
    detail: str | None = None
    session_id: str | None = None
    cwd: str | None = None
    guideline: Guideline | None = field(default=None, compare=False)


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


def _session_duration_minutes(row: sqlite3.Row) -> float | None:
    start = _parse_ts(row["started_at"])
    end = _parse_ts(row["ended_at"])
    if not start or not end:
        return None
    return (end - start).total_seconds() / 60


def _period_filter(since: datetime) -> tuple[str, list[Any]]:
    return "AND s.ended_at >= ?", [_iso(since)]


def analyze_tips(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    focus: str | None = None,
) -> list[Tip]:
    period_start = parse_period(since)
    period_clause, params = _period_filter(period_start)
    focus_norm = focus.lower() if focus else None
    if focus_norm and focus_norm not in FOCUS_AREAS:
        raise ValueError(
            f"Unknown focus {focus!r}. Choose from: {', '.join(sorted(FOCUS_AREAS))}"
        )

    tips: list[Tip] = []

    def include(category: str) -> bool:
        if not focus_norm:
            return True
        mapping = {
            "prompting": {"corrections", "paste"},
            "skills": {"skills"},
            "sessions": {"short_sessions"},
            "planning": {"planning"},
        }
        return category in mapping.get(focus_norm, set())

    # Repeated SKILL.md reads
    if include("skills"):
        gl = get_guideline("skills-on-demand")
        rows = conn.execute(
            f"""
            SELECT s.session_id, s.cwd, s.title, m.repeated_skill_reads, m.skill_reads
            FROM session_metrics m
            JOIN sessions s ON s.session_id = m.session_id
            WHERE s.is_subagent = 0
              AND m.repeated_skill_reads >= 2
              {period_clause}
            ORDER BY m.repeated_skill_reads DESC
            LIMIT 10
            """,
            params,
        ).fetchall()
        for row in rows:
            label = row["title"] or row["session_id"][:8]
            tips.append(
                Tip(
                    category="skills",
                    severity=gl.default_severity,
                    message=f"Same SKILL.md read {row['repeated_skill_reads']} extra time(s) in «{label}»",
                    detail=(
                        f"{row['skill_reads']} total skill reads, "
                        f"{row['repeated_skill_reads']} redundant. "
                        f"{gl.recommendation}"
                    ),
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    # Short session proliferation (same cwd)
    if include("short_sessions"):
        gl = get_guideline("resume-sessions")
        rows = conn.execute(
            f"""
            SELECT s.session_id, s.cwd, s.title, s.started_at, s.ended_at,
                   m.user_turns
            FROM sessions s
            JOIN session_metrics m ON m.session_id = s.session_id
            WHERE s.is_subagent = 0
              {period_clause}
            """,
            params,
        ).fetchall()
        short_by_cwd: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            dur = _session_duration_minutes(row)
            if dur is not None and dur < SHORT_SESSION_MINUTES:
                cwd = row["cwd"] or "unknown"
                short_by_cwd.setdefault(cwd, []).append(row)

        for cwd, sessions in short_by_cwd.items():
            if len(sessions) < 3:
                continue
            tips.append(
                Tip(
                    category="short_sessions",
                    severity=gl.default_severity,
                    message=(
                        f"{len(sessions)} short sessions (<{SHORT_SESSION_MINUTES}m) "
                        f"in {format_path(cwd)}"
                    ),
                    detail=gl.recommendation,
                    cwd=cwd,
                    guideline=gl,
                )
            )

    # High paste ratio vs Read tool usage
    if include("paste"):
        gl = get_guideline("file-reference")
        rows = conn.execute(
            f"""
            SELECT s.session_id, s.cwd, s.title,
                   m.pasted_chars, m.tool_calls,
                   (SELECT COUNT(*) FROM events e
                    WHERE e.session_id = s.session_id
                      AND e.event_type = 'tool_use'
                      AND LOWER(e.tool_name) = 'read') AS read_calls
            FROM session_metrics m
            JOIN sessions s ON s.session_id = m.session_id
            WHERE s.is_subagent = 0
              AND m.pasted_chars >= 1500
              {period_clause}
            ORDER BY m.pasted_chars DESC
            LIMIT 10
            """,
            params,
        ).fetchall()
        for row in rows:
            read_calls = row["read_calls"] or 0
            if read_calls >= 3:
                continue
            label = row["title"] or row["session_id"][:8]
            tips.append(
                Tip(
                    category="paste",
                    severity=gl.default_severity,
                    message=f"~{row['pasted_chars']:,} chars pasted in «{label}» with only {read_calls} @ reads",
                    detail=gl.recommendation,
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    # Correction signals
    if include("corrections"):
        gl = get_guideline("specific-prompts")
        rows = conn.execute(
            f"""
            SELECT s.session_id, s.cwd, s.title, m.correction_signals, m.user_turns
            FROM session_metrics m
            JOIN sessions s ON s.session_id = m.session_id
            WHERE s.is_subagent = 0
              AND m.correction_signals >= 2
              {period_clause}
            ORDER BY m.correction_signals DESC
            LIMIT 10
            """,
            params,
        ).fetchall()
        for row in rows:
            label = row["title"] or row["session_id"][:8]
            tips.append(
                Tip(
                    category="corrections",
                    severity=gl.default_severity,
                    message=(
                        f"{row['correction_signals']} correction signal(s) in «{label}» "
                        f"({row['user_turns']} turns)"
                    ),
                    detail=gl.recommendation,
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    # Multi-step without plan mode (slug proxy)
    if include("planning"):
        gl = get_guideline("plan-mode")
        rows = conn.execute(
            f"""
            SELECT s.session_id, s.cwd, s.title, m.user_turns, m.tool_calls
            FROM session_metrics m
            JOIN sessions s ON s.session_id = m.session_id
            WHERE s.is_subagent = 0
              AND (s.slug IS NULL OR s.slug = '')
              AND m.user_turns >= 4
              AND m.tool_calls >= 8
              {period_clause}
            ORDER BY m.tool_calls DESC
            LIMIT 8
            """,
            params,
        ).fetchall()
        for row in rows:
            label = row["title"] or row["session_id"][:8]
            tips.append(
                Tip(
                    category="planning",
                    severity=gl.default_severity,
                    message=(
                        f"Multi-step session «{label}» — "
                        f"{row['user_turns']} turns, {row['tool_calls']} tool calls"
                    ),
                    detail=gl.recommendation,
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    severity_order = {"high": 0, "medium": 1, "low": 2}
    tips.sort(key=lambda t: severity_order.get(t.severity, 9))
    return tips[:15]


def format_tips(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    focus: str | None = None,
) -> str:
    period_label = since or "24h"
    try:
        tips = analyze_tips(conn, since=since, focus=focus)
    except ValueError as exc:
        return f"Error: {exc}"

    lines = [
        f"## Workflow Tips — since {period_label}",
        "",
        "_Grounded in [Anthropic Claude Code best practices](https://code.claude.com/docs/en/best-practices). Offline analysis._",
        "",
    ]

    if not tips:
        lines.append("_No notable patterns in this period. Keep going!_")
        return "\n".join(lines)

    for i, tip in enumerate(tips, 1):
        badge = {"high": "!!", "medium": "!", "low": "·"}.get(tip.severity, "·")
        lines.append(f"### {i}. [{badge}] {tip.message}")
        if tip.detail:
            lines.append("")
            lines.append(tip.detail)
        if tip.guideline:
            lines.append("")
            gl = tip.guideline
            lines.append(f"**Why**: {gl.detail}")
            lines.append(f"**Source**: [{gl.title}]({gl.source_url})")
        if tip.cwd:
            lines.append(f"**Project**: `{format_path(tip.cwd)}`")
        lines.append("")

    lines.append(f"_{len(tips)} tip(s) found._")
    return "\n".join(lines).rstrip()
