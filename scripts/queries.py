"""SQL queries for standup and search."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from parser import ROLE_WEIGHT


def parse_period(since: str | None) -> datetime:
    now = datetime.now(timezone.utc)
    if not since:
        return now - timedelta(hours=24)

    since = since.strip()
    m = re.fullmatch(r"(\d+)([hdw])", since, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit == "h":
            return now - timedelta(hours=n)
        if unit == "d":
            return now - timedelta(days=n)
        if unit == "w":
            return now - timedelta(weeks=n)

    try:
        if len(since) == 10:
            dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as exc:
        raise ValueError(f"Invalid period: {since!r}") from exc


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def sessions_in_period(
    conn: sqlite3.Connection,
    since: datetime,
    *,
    cwd: str | None = None,
) -> list[sqlite3.Row]:
    query = """
        SELECT *
        FROM sessions
        WHERE is_subagent = 0
          AND ended_at IS NOT NULL
          AND ended_at >= ?
    """
    params: list[Any] = [_iso(since)]
    if cwd:
        query += " AND cwd LIKE ?"
        params.append(f"%{cwd}%")
    query += " ORDER BY ended_at DESC"
    return conn.execute(query, params).fetchall()


def _fts_available(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events_fts'"
    ).fetchone()
    return row is not None


def _fts_match_query(tokens: list[str]) -> str:
    parts = []
    for token in tokens:
        escaped = token.replace('"', '""')
        parts.append(f'"{escaped}"')
    return " AND ".join(parts)


def search_events(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
    project: str | None = None,
) -> list[dict]:
    tokens = [t for t in query.split() if t]
    if not tokens:
        return []

    if _fts_available(conn):
        try:
            results = _search_events_fts(conn, tokens, limit=limit, project=project)
            return results
        except sqlite3.OperationalError:
            pass

    return _search_events_like(conn, tokens, limit=limit, project=project)


def _search_events_fts(
    conn: sqlite3.Connection,
    tokens: list[str],
    *,
    limit: int = 20,
    project: str | None = None,
) -> list[dict]:
    match = _fts_match_query(tokens)
    params: list[Any] = [match]
    sql = """
        SELECT
          s.session_id,
          s.cwd,
          s.title,
          s.ended_at,
          f.role,
          f.text,
          e.timestamp,
          bm25(events_fts) AS rank
        FROM events_fts f
        JOIN events e ON e.id = f.event_id
        JOIN sessions s ON s.session_id = f.session_id
        WHERE events_fts MATCH ?
          AND s.is_subagent = 0
    """
    if project:
        sql += " AND (s.cwd LIKE ? OR s.project_key LIKE ?)"
        params.extend([f"%{project}%", f"%{project}%"])
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit * 8)

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        raise exc

    return _group_search_rows(rows, tokens, limit)


def _search_events_like(
    conn: sqlite3.Connection,
    tokens: list[str],
    *,
    limit: int = 20,
    project: str | None = None,
) -> list[dict]:
    lower_tokens = [t.lower() for t in tokens]
    where = " AND ".join(["LOWER(e.text) LIKE ?"] * len(lower_tokens))
    params: list[Any] = [f"%{t}%" for t in lower_tokens]

    sql = f"""
        SELECT
          s.session_id,
          s.cwd,
          s.title,
          s.ended_at,
          e.role,
          e.text,
          e.timestamp
        FROM events e
        JOIN sessions s ON s.session_id = e.session_id
        WHERE s.is_subagent = 0
          AND e.text IS NOT NULL
          AND {where}
    """
    if project:
        sql += " AND (s.cwd LIKE ? OR s.project_key LIKE ?)"
        params.extend([f"%{project}%", f"%{project}%"])

    rows = conn.execute(sql, params).fetchall()
    return _group_search_rows(rows, lower_tokens, limit)


def _group_search_rows(
    rows: list[sqlite3.Row],
    tokens: list[str],
    limit: int,
) -> list[dict]:
    grouped: dict[str, dict] = {}

    for row in rows:
        sid = row["session_id"]
        role = row["role"] or "assistant"
        weight = ROLE_WEIGHT.get(role, 1)
        if sid not in grouped:
            grouped[sid] = {
                "session_id": sid,
                "cwd": row["cwd"],
                "title": row["title"],
                "ended_at": row["ended_at"],
                "score": 0.0,
                "matches": [],
            }
        grouped[sid]["score"] += weight
        if len(grouped[sid]["matches"]) < 3:
            grouped[sid]["matches"].append((role, _snippet(row["text"], tokens)))

    results = sorted(
        grouped.values(),
        key=lambda x: (x["score"], x["ended_at"] or ""),
        reverse=True,
    )
    return results[:limit]


def token_totals_by_session(
    conn: sqlite3.Connection,
    since_iso: str,
    *,
    include_subagents: bool = False,
) -> list[sqlite3.Row]:
    subagent_clause = "" if include_subagents else "AND s.is_subagent = 0"
    return conn.execute(
        f"""
        SELECT
          s.session_id,
          s.cwd,
          s.title,
          s.ended_at,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.cache_create_tokens), 0) AS cache_create_tokens
        FROM sessions s
        LEFT JOIN token_usage t ON t.session_id = s.session_id
        WHERE s.ended_at >= ?
          {subagent_clause}
        GROUP BY s.session_id
        HAVING (input_tokens + output_tokens + cache_read_tokens + cache_create_tokens) > 0
        ORDER BY (input_tokens + cache_read_tokens + cache_create_tokens) DESC
        """,
        (since_iso,),
    ).fetchall()


def token_totals_by_day(
    conn: sqlite3.Connection,
    since_iso: str,
    *,
    include_subagents: bool = False,
) -> list[dict]:
    subagent_clause = "" if include_subagents else "AND s.is_subagent = 0"
    rows = conn.execute(
        f"""
        SELECT
          DATE(t.timestamp) AS day,
          COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
          COALESCE(SUM(t.output_tokens), 0) AS output_tokens,
          COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(t.cache_create_tokens), 0) AS cache_create_tokens
        FROM token_usage t
        JOIN sessions s ON s.session_id = t.session_id
        WHERE t.timestamp >= ?
          {subagent_clause}
        GROUP BY day
        ORDER BY day DESC
        """,
        (since_iso,),
    ).fetchall()
    return [dict(r) for r in rows]


def tool_usage_totals(
    conn: sqlite3.Connection,
    since_iso: str,
    *,
    include_subagents: bool = False,
) -> list[dict]:
    subagent_clause = "" if include_subagents else "AND s.is_subagent = 0"
    rows = conn.execute(
        f"""
        SELECT e.tool_name, COUNT(*) AS calls
        FROM events e
        JOIN sessions s ON s.session_id = e.session_id
        WHERE e.event_type = 'tool_use'
          AND e.tool_name IS NOT NULL
          AND s.ended_at >= ?
          {subagent_clause}
        GROUP BY e.tool_name
        ORDER BY calls DESC
        LIMIT 15
        """,
        (since_iso,),
    ).fetchall()
    return [dict(r) for r in rows]


def bash_heavy_sessions(
    conn: sqlite3.Connection,
    since_iso: str,
    *,
    include_subagents: bool = False,
    min_bash_calls: int = 20,
    min_bash_ratio: float = 0.45,
) -> list[dict]:
    subagent_clause = "" if include_subagents else "AND s.is_subagent = 0"
    rows = conn.execute(
        f"""
        SELECT
          s.session_id, s.cwd, s.title,
          SUM(CASE WHEN e.tool_name = 'Bash' THEN 1 ELSE 0 END) AS bash_calls,
          COUNT(*) AS total_calls,
          SUM(CASE
            WHEN e.tool_name = 'Bash'
              AND (e.tool_input LIKE '%"cat %'
                OR e.tool_input LIKE '%"head %'
                OR e.tool_input LIKE '%"tail %'
                OR e.tool_input LIKE '% cat %'
                OR e.tool_input LIKE '% head %'
                OR e.tool_input LIKE '% tail %')
            THEN 1 ELSE 0 END) AS file_read_bash
        FROM events e
        JOIN sessions s ON s.session_id = e.session_id
        WHERE e.event_type = 'tool_use'
          AND s.ended_at >= ?
          {subagent_clause}
        GROUP BY s.session_id
        HAVING bash_calls >= ?
           AND CAST(bash_calls AS REAL) / NULLIF(total_calls, 0) >= ?
        ORDER BY bash_calls DESC
        LIMIT 6
        """,
        (since_iso, min_bash_calls, min_bash_ratio),
    ).fetchall()
    return [dict(r) for r in rows]


def agent_heavy_sessions(
    conn: sqlite3.Connection,
    since_iso: str,
    *,
    include_subagents: bool = False,
    min_agent_calls: int = 5,
) -> list[dict]:
    subagent_clause = "" if include_subagents else "AND s.is_subagent = 0"
    rows = conn.execute(
        f"""
        SELECT
          s.session_id, s.cwd, s.title,
          COUNT(*) AS agent_calls
        FROM events e
        JOIN sessions s ON s.session_id = e.session_id
        WHERE e.event_type = 'tool_use'
          AND e.tool_name = 'Agent'
          AND s.ended_at >= ?
          {subagent_clause}
        GROUP BY s.session_id
        HAVING agent_calls >= ?
        ORDER BY agent_calls DESC
        LIMIT 6
        """,
        (since_iso, min_agent_calls),
    ).fetchall()
    return [dict(r) for r in rows]


def _snippet(text: str, tokens: list[str], max_len: int = 200) -> str:
    snippet = text.strip().replace("\n", " ")
    if len(snippet) <= max_len:
        return snippet
    lower = snippet.lower()
    idx = min((lower.find(t) for t in tokens if lower.find(t) != -1), default=0)
    start = max(0, idx - max_len // 3)
    end = min(len(snippet), start + max_len)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(snippet) else ""
    return prefix + snippet[start:end] + suffix
