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


def search_events(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
    project: str | None = None,
) -> list[dict]:
    tokens = [t.lower() for t in query.split() if t]
    if not tokens:
        return []

    where = " AND ".join(["LOWER(e.text) LIKE ?"] * len(tokens))
    params: list[Any] = [f"%{t}%" for t in tokens]

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
