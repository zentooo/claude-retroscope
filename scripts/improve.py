"""Friction-signal analysis → CLAUDE.md improvement suggestions (offline).

Detects recurring friction in past sessions (repeated build/test errors and
repeated user course-corrections) and maps each pattern to a candidate
instruction-file rule. Inspired by GitHub Copilot CLI's `/chronicle improve`,
but reads Claude Code's JSONL index and stays fully offline.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from guidelines import Guideline, get as get_guideline
from metrics import CORRECTION_PATTERNS
from paths import format_path
from queries import _iso, parse_period

DEFAULT_SINCE = "7d"
MIN_RECURRENCE = 2
FOCUS_AREAS = frozenset({"errors", "corrections"})

# Lines worth treating as an error signature.
_FAILURE_RE = re.compile(
    r"(error|failed|failure|exception|traceback|fatal|not found|"
    r"cannot find|undefined|npm err|panic|assert)",
    re.IGNORECASE,
)

# Best-effort directive extraction: "use X instead of Y", "X ではなく Y", ...
_TOOL_PREF_RES = [
    re.compile(
        r"use\s+(?P<want>[\w./@+-]+)\s+(?:instead of|rather than|not)\s+(?P<avoid>[\w./@+-]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"should be\s+(?P<want>[\w./@+-]+)\s+not\s+(?P<avoid>[\w./@+-]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<avoid>[\w./@+-]+)\s*(?:ではなく|じゃなくて|ではなくて)\s*(?P<want>[\w./@+-]+)"
    ),
]

_PATH_RE = re.compile(r"(?:/[\w.@+-]+){2,}")
_HEX_RE = re.compile(r"0x[0-9a-f]+", re.IGNORECASE)
_NUM_RE = re.compile(r"\d+")


@dataclass
class FrictionSignal:
    kind: str  # recurring_error | tool_preference | repeated_correction
    cwd: str
    summary: str
    count: int
    sessions: list[str]
    examples: list[str] = field(default_factory=list)
    guideline: Guideline | None = field(default=None, compare=False)


def _error_signature(source: str) -> str | None:
    """Normalize an error blob into a stable signature for grouping."""
    candidates = source.splitlines() if "\n" in source else [source]
    for raw in candidates:
        line = raw.strip()
        if not line or not _FAILURE_RE.search(line):
            continue
        norm = _PATH_RE.sub("…", line)
        norm = _HEX_RE.sub("0x…", norm)
        norm = _NUM_RE.sub("#", norm)
        norm = " ".join(norm.split())
        return norm[:120]
    return None


def _extract_directive(text: str) -> str | None:
    for rx in _TOOL_PREF_RES:
        m = rx.search(text)
        if m:
            return f"Use `{m.group('want')}` instead of `{m.group('avoid')}`"
    return None


def _recurring_errors(
    conn: sqlite3.Connection,
    start_iso: str,
    end_iso: str,
    subagent_clause: str,
    project_clause: str,
    project_params: list[Any],
) -> list[FrictionSignal]:
    rows = conn.execute(
        f"""
        SELECT e.session_id, s.cwd, e.text, e.stderr
        FROM events e
        JOIN sessions s ON s.session_id = e.session_id
        WHERE e.is_error = 1
          AND s.ended_at >= ? AND s.ended_at <= ?
          {subagent_clause}
          {project_clause}
        """,
        [start_iso, end_iso, *project_params],
    ).fetchall()

    buckets: dict[tuple[str, str], dict] = {}
    for row in rows:
        source = row["stderr"] or row["text"] or ""
        sig = _error_signature(source)
        if not sig:
            continue
        key = (row["cwd"] or "unknown", sig)
        bucket = buckets.setdefault(
            key, {"count": 0, "sessions": set(), "examples": []}
        )
        bucket["count"] += 1
        bucket["sessions"].add(row["session_id"])
        if len(bucket["examples"]) < 2:
            bucket["examples"].append(" ".join(source.split())[:200])

    gl = get_guideline("document-recurring-errors")
    signals: list[FrictionSignal] = []
    for (cwd, sig), bucket in buckets.items():
        if bucket["count"] < MIN_RECURRENCE:
            continue
        signals.append(
            FrictionSignal(
                kind="recurring_error",
                cwd=cwd,
                summary=sig,
                count=bucket["count"],
                sessions=sorted(bucket["sessions"]),
                examples=bucket["examples"],
                guideline=gl,
            )
        )
    return signals


def _repeated_corrections(
    conn: sqlite3.Connection,
    start_iso: str,
    end_iso: str,
    subagent_clause: str,
    project_clause: str,
    project_params: list[Any],
) -> list[FrictionSignal]:
    rows = conn.execute(
        f"""
        SELECT e.session_id, s.cwd, e.text
        FROM events e
        JOIN sessions s ON s.session_id = e.session_id
        WHERE e.event_type = 'user' AND e.text IS NOT NULL
          AND s.ended_at >= ? AND s.ended_at <= ?
          {subagent_clause}
          {project_clause}
        """,
        [start_iso, end_iso, *project_params],
    ).fetchall()

    def _new_slot() -> dict:
        return {
            "sessions": set(),
            "examples": [],
            "directives": defaultdict(lambda: {"count": 0, "sessions": set()}),
        }

    by_cwd: dict[str, dict] = defaultdict(_new_slot)
    for row in rows:
        text = row["text"]
        if not text:
            continue
        directive = _extract_directive(text)
        if not (directive or CORRECTION_PATTERNS.search(text)):
            continue
        slot = by_cwd[row["cwd"] or "unknown"]
        slot["sessions"].add(row["session_id"])
        if len(slot["examples"]) < 3:
            slot["examples"].append(" ".join(text.split())[:200])
        if directive:
            entry = slot["directives"][directive]
            entry["count"] += 1
            entry["sessions"].add(row["session_id"])

    gl = get_guideline("encode-corrections")
    signals: list[FrictionSignal] = []
    for cwd, slot in by_cwd.items():
        for directive, entry in slot["directives"].items():
            if len(entry["sessions"]) >= MIN_RECURRENCE or entry["count"] >= MIN_RECURRENCE:
                signals.append(
                    FrictionSignal(
                        kind="tool_preference",
                        cwd=cwd,
                        summary=directive,
                        count=max(entry["count"], len(entry["sessions"])),
                        sessions=sorted(entry["sessions"]),
                        guideline=gl,
                    )
                )
        if len(slot["sessions"]) >= MIN_RECURRENCE:
            signals.append(
                FrictionSignal(
                    kind="repeated_correction",
                    cwd=cwd,
                    summary=f"{len(slot['sessions'])} sessions needed course-corrections",
                    count=len(slot["sessions"]),
                    sessions=sorted(slot["sessions"]),
                    examples=slot["examples"],
                    guideline=gl,
                )
            )
    return signals


def analyze_friction(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    stable_days: int = 0,
    project: str | None = None,
    focus: str | None = None,
    include_subagents: bool = False,
) -> list[FrictionSignal]:
    period_start = parse_period(since or DEFAULT_SINCE)
    now = datetime.now(timezone.utc)
    window_end = now - timedelta(days=stable_days) if stable_days > 0 else now
    start_iso, end_iso = _iso(period_start), _iso(window_end)

    focus_norm = focus.lower() if focus else None
    if focus_norm and focus_norm not in FOCUS_AREAS:
        raise ValueError(
            f"Unknown focus {focus!r}. Choose from: {', '.join(sorted(FOCUS_AREAS))}"
        )

    subagent_clause = "" if include_subagents else "AND s.is_subagent = 0"
    project_clause = ""
    project_params: list[Any] = []
    if project:
        project_clause = "AND (s.cwd LIKE ? OR s.project_key LIKE ?)"
        project_params = [f"%{project}%", f"%{project}%"]

    signals: list[FrictionSignal] = []
    if not focus_norm or focus_norm == "errors":
        signals += _recurring_errors(
            conn, start_iso, end_iso, subagent_clause, project_clause, project_params
        )
    if not focus_norm or focus_norm == "corrections":
        signals += _repeated_corrections(
            conn, start_iso, end_iso, subagent_clause, project_clause, project_params
        )

    severity_order = {"high": 0, "medium": 1, "low": 2}

    def sort_key(sig: FrictionSignal) -> tuple[int, int]:
        sev = sig.guideline.default_severity if sig.guideline else "low"
        return severity_order.get(sev, 9), -sig.count

    signals.sort(key=sort_key)
    return signals


def _instruction_target(cwd: str) -> tuple[str, bool]:
    """Return (path, exists) for the best CLAUDE.md target of a project."""
    if not cwd or cwd == "unknown":
        global_md = Path.home() / ".claude" / "CLAUDE.md"
        return str(global_md), global_md.exists()
    base = Path(cwd)
    for candidate in (base / "CLAUDE.md", base / ".claude" / "CLAUDE.md"):
        if candidate.exists():
            return str(candidate), True
    return str(base / "CLAUDE.md"), False


_BADGE = {"high": "!!", "medium": "!", "low": "·"}


def format_improve(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    stable_days: int = 0,
    project: str | None = None,
    focus: str | None = None,
    include_subagents: bool = False,
) -> str:
    period_label = since or DEFAULT_SINCE
    try:
        signals = analyze_friction(
            conn,
            since=since,
            stable_days=stable_days,
            project=project,
            focus=focus,
            include_subagents=include_subagents,
        )
    except ValueError as exc:
        return f"Error: {exc}"

    lines = [
        f"## Improvement Suggestions — since {period_label}",
        "",
        "_Recurring friction from past sessions, mapped to candidate CLAUDE.md rules. "
        "Offline analysis grounded in "
        "[Anthropic Claude Code best practices](https://code.claude.com/docs/en/best-practices)._",
        "",
    ]
    if stable_days > 0:
        lines.append(
            f"_Excluding the most recent {stable_days} day(s) to skip incident-response noise._"
        )
        lines.append("")

    if not signals:
        lines.append(
            "_No recurring friction detected in this period. Nothing to encode right now._"
        )
        return "\n".join(lines).rstrip()

    by_cwd: dict[str, list[FrictionSignal]] = defaultdict(list)
    for sig in signals:
        by_cwd[sig.cwd].append(sig)

    for cwd in sorted(by_cwd):
        sigs = by_cwd[cwd]
        target, exists = _instruction_target(cwd)
        lines.append(f"### {format_path(cwd)}")
        verb = "Update" if exists else "Create"
        suffix = "" if exists else " _(does not exist yet)_"
        lines.append(f"_{verb}_ `{format_path(target)}`{suffix}")
        lines.append("")

        for sig in sigs:
            badge = _BADGE.get(
                sig.guideline.default_severity if sig.guideline else "low", "·"
            )
            if sig.kind == "recurring_error":
                lines.append(
                    f"- [{badge}] **Recurring error ×{sig.count}**: `{sig.summary}`"
                )
                lines.append(f"  - Suggested rule: _Note this failure and its fix in CLAUDE.md._")
            elif sig.kind == "tool_preference":
                lines.append(
                    f"- [{badge}] **Repeated correction ×{sig.count}**: {sig.summary}"
                )
                lines.append(f"  - Suggested rule: _{sig.summary}._")
            else:
                lines.append(f"- [{badge}] **{sig.summary}**")
            for ex in sig.examples[:2]:
                lines.append(f"    - e.g. “{ex}”")

        guideline = next((s.guideline for s in sigs if s.guideline), None)
        if guideline:
            lines.append("")
            lines.append(f"**Why**: {guideline.detail}")
            lines.append(f"**Source**: [{guideline.title}]({guideline.source_url})")
        lines.append("")

    lines.append(
        f"_{len(signals)} signal(s) across {len(by_cwd)} project(s). "
        "Review and add the rules you agree with — suggestions are heuristic, not auto-applied._"
    )
    return "\n".join(lines).rstrip()
