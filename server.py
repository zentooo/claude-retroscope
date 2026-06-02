# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=1.0"]
# ///

"""Retroscope MCP server — structured session analysis for Claude Code."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from mcp.server.fastmcp import FastMCP

from cost import format_cost_tips
from ingest import ingest_all, reindex
from search_fmt import format_search
from standup import format_standup
from store import db_stats, ensure_db
from tips import format_tips

mcp = FastMCP("retroscope")


def _refresh(include_subagents: bool = False) -> None:
    ingest_all(include_subagents=include_subagents)


@mcp.tool()
def retroscope_standup(since: str | None = None, include_subagents: bool = False) -> str:
    """Generate a structured work recap from indexed Claude Code sessions.

    Args:
        since: Time period like 24h, 3d, 7d, or ISO date. Default 24h.
        include_subagents: Include subagent session logs.
    """
    _refresh(include_subagents)
    conn = ensure_db()
    return format_standup(conn, since=since)


@mcp.tool()
def retroscope_search(
    query: str,
    limit: int = 20,
    project: str | None = None,
    include_subagents: bool = False,
) -> str:
    """Full-text search across indexed Claude Code session contents."""
    _refresh(include_subagents)
    conn = ensure_db()
    return format_search(conn, query, limit=limit, project=project)


@mcp.tool()
def retroscope_tips(
    since: str | None = None,
    focus: str | None = None,
    include_subagents: bool = False,
) -> str:
    """Analyze workflow patterns and suggest actionable improvements (offline).

    Args:
        since: Time period like 24h, 3d, 7d, or ISO date. Default 24h.
        focus: Optional category — prompting, skills, sessions, planning.
        include_subagents: Include subagent session logs.
    """
    _refresh(include_subagents)
    conn = ensure_db()
    return format_tips(conn, since=since, focus=focus)


@mcp.tool()
def retroscope_cost_tips(
    since: str | None = None,
    focus: str | None = None,
    include_subagents: bool = False,
) -> str:
    """Analyze token usage and suggest cost-reduction tips (offline).

    Args:
        since: Time period like 24h, 3d, 7d, or ISO date. Default 24h.
        focus: Optional category — cache, sessions, skills, subagents.
        include_subagents: Include subagent session logs.
    """
    _refresh(include_subagents)
    conn = ensure_db()
    return format_cost_tips(
        conn, since=since, focus=focus, include_subagents=include_subagents
    )


@mcp.tool()
def retroscope_status(include_subagents: bool = False) -> str:
    """Show Retroscope index status (sessions, events, pending ingest)."""
    conn = ensure_db()
    stats = db_stats(conn)
    pending = ingest_all(include_subagents=include_subagents)["pending_files"]
    return (
        f"Sessions: {stats['sessions']}\n"
        f"Events: {stats['events']}\n"
        f"Token rows: {stats['token_rows']}\n"
        f"Metrics: {stats['metrics_rows']}\n"
        f"FTS indexed: {stats['fts_rows']}\n"
        f"Ingested files: {stats['ingested_files']}\n"
        f"Last ingest: {stats['last_ingest_at'] or 'never'}\n"
        f"Pending files: {pending}"
    )


@mcp.tool()
def retroscope_reindex(include_subagents: bool = False) -> str:
    """Rebuild the Retroscope index from Claude Code JSONL logs."""
    stats = reindex(include_subagents=include_subagents)
    return (
        f"Reindexed {stats['files_scanned']} files, "
        f"{stats['lines_ingested']} lines ingested."
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
