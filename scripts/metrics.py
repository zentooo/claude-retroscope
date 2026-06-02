"""Compute session_metrics from indexed events."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter

SKILL_PATH_RE = re.compile(r"SKILL\.md", re.IGNORECASE)
CORRECTION_PATTERNS = re.compile(
    r"(?:"
    r"いいえ|違う|間違|やり直|もう一度|"
    r"no,? that(?:'s| is) (?:wrong|incorrect)|"
    r"not what i (?:meant|asked)|"
    r"try again|redo|start over|"
    r"instead use|should be \w+ not"
    r")",
    re.IGNORECASE,
)
PASTE_CHAR_THRESHOLD = 500


def _skill_path_from_input(tool_input: str | None) -> str | None:
    if not tool_input:
        return None
    try:
        data = json.loads(tool_input)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        for key in ("file_path", "path", "target_file"):
            val = data.get(key)
            if isinstance(val, str) and SKILL_PATH_RE.search(val):
                return val
    if SKILL_PATH_RE.search(tool_input):
        return tool_input
    return None


def compute_session_metrics(conn: sqlite3.Connection, session_id: str) -> dict:
    user_turns = conn.execute(
        """
        SELECT COUNT(*) FROM events
        WHERE session_id = ? AND event_type = 'user'
        """,
        (session_id,),
    ).fetchone()[0]

    tool_rows = conn.execute(
        """
        SELECT tool_name, tool_input, text
        FROM events
        WHERE session_id = ? AND event_type = 'tool_use'
        """,
        (session_id,),
    ).fetchall()
    tool_calls = len(tool_rows)

    read_rows = [r for r in tool_rows if (r["tool_name"] or "").lower() == "read"]
    skill_paths: list[str] = []
    for row in read_rows:
        path = _skill_path_from_input(row["tool_input"])
        if path:
            skill_paths.append(path)

    skill_reads = len(skill_paths)
    path_counts = Counter(skill_paths)
    repeated_skill_reads = sum(max(0, c - 1) for c in path_counts.values())

    user_texts = conn.execute(
        """
        SELECT text FROM events
        WHERE session_id = ? AND event_type = 'user' AND text IS NOT NULL
        """,
        (session_id,),
    ).fetchall()
    pasted_chars = sum(
        len(r["text"])
        for r in user_texts
        if r["text"] and len(r["text"]) >= PASTE_CHAR_THRESHOLD
    )

    correction_signals = 0
    for row in user_texts:
        if row["text"] and CORRECTION_PATTERNS.search(row["text"]):
            correction_signals += 1

    return {
        "session_id": session_id,
        "user_turns": user_turns,
        "tool_calls": tool_calls,
        "skill_reads": skill_reads,
        "repeated_skill_reads": repeated_skill_reads,
        "pasted_chars": pasted_chars,
        "correction_signals": correction_signals,
    }


def upsert_session_metrics(conn: sqlite3.Connection, session_id: str) -> None:
    m = compute_session_metrics(conn, session_id)
    conn.execute(
        """
        INSERT INTO session_metrics (
          session_id, user_turns, tool_calls, skill_reads,
          repeated_skill_reads, pasted_chars, correction_signals
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          user_turns = excluded.user_turns,
          tool_calls = excluded.tool_calls,
          skill_reads = excluded.skill_reads,
          repeated_skill_reads = excluded.repeated_skill_reads,
          pasted_chars = excluded.pasted_chars,
          correction_signals = excluded.correction_signals
        """,
        (
            m["session_id"],
            m["user_turns"],
            m["tool_calls"],
            m["skill_reads"],
            m["repeated_skill_reads"],
            m["pasted_chars"],
            m["correction_signals"],
        ),
    )


def refresh_metrics(
    conn: sqlite3.Connection,
    session_ids: list[str] | None = None,
) -> int:
    if session_ids is None:
        rows = conn.execute("SELECT session_id FROM sessions").fetchall()
        session_ids = [r["session_id"] for r in rows]
    for sid in session_ids:
        upsert_session_metrics(conn, sid)
    return len(session_ids)
