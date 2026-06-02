"""Token cost analysis and cost-reduction tips."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from guidelines import Guideline, get as get_guideline
from paths import format_path
from queries import (
    _iso,
    agent_heavy_sessions,
    bash_heavy_sessions,
    parse_period,
    token_totals_by_day,
    token_totals_by_session,
    tool_usage_totals,
)

FOCUS_AREAS = frozenset({"cache", "sessions", "skills", "subagents", "tools"})


@dataclass
class CostTip:
    category: str
    severity: str
    message: str
    detail: str | None = None
    session_id: str | None = None
    cwd: str | None = None
    guideline: Guideline | None = field(default=None, compare=False)


def analyze_cost_tips(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    focus: str | None = None,
    include_subagents: bool = False,
) -> list[CostTip]:
    period_start = parse_period(since)
    since_iso = _iso(period_start)
    focus_norm = focus.lower() if focus else None
    if focus_norm and focus_norm not in FOCUS_AREAS:
        raise ValueError(
            f"Unknown focus {focus!r}. Choose from: {', '.join(sorted(FOCUS_AREAS))}"
        )

    tips: list[CostTip] = []
    subagent_clause = "" if include_subagents else "AND s.is_subagent = 0"

    def include(category: str) -> bool:
        if not focus_norm:
            return True
        mapping = {
            "cache": {"cache"},
            "sessions": {"long_sessions", "daily"},
            "skills": {"skills"},
            "subagents": {"subagents"},
            "tools": {"bash_heavy", "agent_heavy"},
        }
        return category in mapping.get(focus_norm, set())

    session_totals = token_totals_by_session(
        conn, since_iso, include_subagents=include_subagents
    )

    # High cache_create ratio
    if include("cache"):
        gl = get_guideline("compact-context")
        for row in session_totals:
            total_in = (row["input_tokens"] or 0) + (row["cache_read_tokens"] or 0)
            cache_create = row["cache_create_tokens"] or 0
            if total_in < 50000:
                continue
            ratio = cache_create / total_in if total_in else 0
            if ratio < 0.25:
                continue
            label = row["title"] or row["session_id"][:8]
            tips.append(
                CostTip(
                    category="cache",
                    severity=gl.default_severity,
                    message=f"High cache creation in «{label}» ({ratio:.0%} of input, {cache_create:,} tokens)",
                    detail=gl.recommendation,
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    # Long sessions (turns x tokens)
    if include("long_sessions"):
        gl = get_guideline("session-length")
        rows = conn.execute(
            f"""
            SELECT s.session_id, s.cwd, s.title, m.user_turns,
                   COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(t.output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read,
                   COALESCE(SUM(t.cache_create_tokens), 0) AS cache_create
            FROM sessions s
            JOIN session_metrics m ON m.session_id = s.session_id
            LEFT JOIN token_usage t ON t.session_id = s.session_id
            WHERE s.ended_at >= ?
              {subagent_clause}
            GROUP BY s.session_id
            HAVING m.user_turns >= 15
               AND (input_tokens + cache_read + cache_create) >= 200000
            ORDER BY (input_tokens + cache_read + cache_create) DESC
            LIMIT 8
            """,
            (since_iso,),
        ).fetchall()
        for row in rows:
            total = (
                (row["input_tokens"] or 0)
                + (row["cache_read"] or 0)
                + (row["cache_create"] or 0)
            )
            label = row["title"] or row["session_id"][:8]
            tips.append(
                CostTip(
                    category="long_sessions",
                    severity=gl.default_severity,
                    message=f"Long session «{label}» — {row['user_turns']} turns, ~{total:,} input tokens",
                    detail=gl.recommendation,
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    # Repeated skill reads + high cache_create
    if include("skills"):
        gl = get_guideline("skills-on-demand")
        rows = conn.execute(
            f"""
            SELECT s.session_id, s.cwd, s.title,
                   m.repeated_skill_reads,
                   COALESCE(SUM(t.cache_create_tokens), 0) AS cache_create
            FROM sessions s
            JOIN session_metrics m ON m.session_id = s.session_id
            LEFT JOIN token_usage t ON t.session_id = s.session_id
            WHERE s.ended_at >= ?
              {subagent_clause}
              AND m.repeated_skill_reads >= 2
            GROUP BY s.session_id
            HAVING cache_create >= 30000
            ORDER BY cache_create DESC
            LIMIT 6
            """,
            (since_iso,),
        ).fetchall()
        for row in rows:
            label = row["title"] or row["session_id"][:8]
            tips.append(
                CostTip(
                    category="skills",
                    severity=gl.default_severity,
                    message=(
                        f"Repeated skill reads added cache cost in «{label}» — "
                        f"{row['repeated_skill_reads']} redundant reads, "
                        f"cache_create={row['cache_create']:,}"
                    ),
                    detail=gl.recommendation,
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    # Subagent token cost
    if include("subagents") and include_subagents:
        gl = get_guideline("subagent-scope")
        rows = conn.execute(
            """
            SELECT s.session_id, s.cwd, s.title,
                   COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(t.output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(t.cache_create_tokens), 0) AS cache_create
            FROM sessions s
            LEFT JOIN token_usage t ON t.session_id = s.session_id
            WHERE s.is_subagent = 1
              AND s.ended_at >= ?
            GROUP BY s.session_id
            HAVING (input_tokens + cache_create) >= 50000
            ORDER BY (input_tokens + cache_create) DESC
            LIMIT 6
            """,
            (since_iso,),
        ).fetchall()
        for row in rows:
            total = (row["input_tokens"] or 0) + (row["cache_create"] or 0)
            label = row["title"] or row["session_id"][:8]
            tips.append(
                CostTip(
                    category="subagents",
                    severity=gl.default_severity,
                    message=f"Subagent «{label}» used ~{total:,} input tokens",
                    detail=gl.recommendation,
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    # Bash-heavy sessions
    if include("bash_heavy"):
        gl = get_guideline("bash-over-read")
        for row in bash_heavy_sessions(
            conn, since_iso, include_subagents=include_subagents
        ):
            label = row["title"] or row["session_id"][:8]
            bash_pct = int(row["bash_calls"] * 100 / max(row["total_calls"], 1))
            detail = gl.recommendation
            if row["file_read_bash"]:
                detail = (
                    f"{row['file_read_bash']} Bash call(s) used cat/head/tail — "
                    f"consider Read instead. " + detail
                )
            tips.append(
                CostTip(
                    category="bash_heavy",
                    severity=gl.default_severity,
                    message=(
                        f"Bash-heavy session «{label}» — "
                        f"{row['bash_calls']} Bash calls ({bash_pct}% of {row['total_calls']} total)"
                    ),
                    detail=detail,
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    # Agent-heavy sessions
    if include("agent_heavy"):
        gl = get_guideline("agent-tool-cost")
        for row in agent_heavy_sessions(
            conn, since_iso, include_subagents=include_subagents
        ):
            label = row["title"] or row["session_id"][:8]
            tips.append(
                CostTip(
                    category="agent_heavy",
                    severity=gl.default_severity,
                    message=(
                        f"Many Agent spawns in «{label}» — "
                        f"{row['agent_calls']} Agent tool calls"
                    ),
                    detail=gl.recommendation,
                    session_id=row["session_id"],
                    cwd=row["cwd"],
                    guideline=gl,
                )
            )

    severity_order = {"high": 0, "medium": 1, "low": 2}
    tips.sort(key=lambda t: severity_order.get(t.severity, 9))
    return tips[:12]


def format_cost_tips(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    focus: str | None = None,
    include_subagents: bool = False,
) -> str:
    period_label = since or "24h"
    period_start = parse_period(since)
    since_iso = _iso(period_start)

    lines = [
        f"## Cost Tips — since {period_label}",
        "",
        "_Grounded in [Anthropic Claude Code best practices](https://code.claude.com/docs/en/best-practices). Offline token analysis._",
        "",
    ]

    # Summary table
    daily = token_totals_by_day(conn, since_iso, include_subagents=include_subagents)
    if daily:
        lines.append("### Daily token usage")
        lines.append("")
        lines.append("| Date | Input | Output | Cache read | Cache create |")
        lines.append("|------|------:|-------:|-----------:|-------------:|")
        for row in daily[:14]:
            lines.append(
                f"| {row['day']} "
                f"| {(row['input_tokens'] or 0):,} "
                f"| {(row['output_tokens'] or 0):,} "
                f"| {(row['cache_read_tokens'] or 0):,} "
                f"| {(row['cache_create_tokens'] or 0):,} |"
            )
        lines.append("")

    tool_totals = tool_usage_totals(conn, since_iso, include_subagents=include_subagents)
    if tool_totals:
        total_calls = sum(r["calls"] for r in tool_totals)
        lines.append("### Tool call breakdown")
        lines.append("")
        lines.append("| Tool | Calls | % |")
        lines.append("|------|------:|--:|")
        for row in tool_totals:
            pct = row["calls"] * 100 // max(total_calls, 1)
            lines.append(f"| {row['tool_name']} | {row['calls']:,} | {pct}% |")
        lines.append(f"| **Total** | **{total_calls:,}** | 100% |")
        lines.append("")

    session_totals = token_totals_by_session(
        conn, since_iso, include_subagents=include_subagents
    )
    if session_totals:
        top = session_totals[:5]
        lines.append("### Top sessions by input tokens")
        lines.append("")
        for row in top:
            total_in = (
                (row["input_tokens"] or 0)
                + (row["cache_read_tokens"] or 0)
                + (row["cache_create_tokens"] or 0)
            )
            label = row["title"] or row["session_id"][:8]
            cwd = format_path(row["cwd"])
            lines.append(
                f"- **{label}** ({cwd}): {total_in:,} input "
                f"(out {(row['output_tokens'] or 0):,})"
            )
        lines.append("")

    try:
        tips = analyze_cost_tips(
            conn,
            since=since,
            focus=focus,
            include_subagents=include_subagents,
        )
    except ValueError as exc:
        lines.append(f"Error: {exc}")
        return "\n".join(lines)

    if tips:
        lines.append("### Recommendations")
        lines.append("")
        for i, tip in enumerate(tips, 1):
            badge = {"high": "!!", "medium": "!", "low": "·"}.get(tip.severity, "·")
            lines.append(f"**{i}. [{badge}] {tip.message}**")
            if tip.detail:
                lines.append("")
                lines.append(tip.detail)
            if tip.guideline:
                gl = tip.guideline
                lines.append("")
                lines.append(f"**Why**: {gl.detail}")
                lines.append(f"**Source**: [{gl.title}]({gl.source_url})")
            if tip.cwd:
                lines.append(f"**Project**: `{format_path(tip.cwd)}`")
            lines.append("")
    elif not daily and not session_totals:
        lines.append("_No token usage data in this period._")
    else:
        lines.append("_No cost issues detected — usage looks reasonable._")

    return "\n".join(lines).rstrip()
