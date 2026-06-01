"""Incremental JSONL ingest into SQLite index."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from parser import LineParseResult, parse_jsonl_line
from paths import projects_dir
from store import ensure_db, utc_now as _utc_now


def _is_subagent_path(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return "subagents" in parts or path.stem.startswith("agent-")


def discover_jsonl_files(
    root: Path | None = None,
    *,
    include_subagents: bool = False,
) -> list[Path]:
    base = root or projects_dir()
    if not base.exists():
        return []
    files = sorted(base.rglob("*.jsonl"))
    if include_subagents:
        return files
    return [f for f in files if not _is_subagent_path(f)]


def _session_id_from_path(path: Path, project_key: str) -> tuple[str, str, bool]:
    session_id = path.stem
    is_subagent = _is_subagent_path(path)
    return session_id, project_key, is_subagent


def _project_key(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
        if rel.parts:
            return rel.parts[0]
    except ValueError:
        pass
    return path.parent.name


def _ensure_session(
    conn: sqlite3.Connection,
    session_id: str,
    project_key: str,
    is_subagent: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO sessions (session_id, project_key, is_subagent, source)
        VALUES (?, ?, ?, 'cli')
        ON CONFLICT(session_id) DO UPDATE SET
          project_key = excluded.project_key,
          is_subagent = excluded.is_subagent
        """,
        (session_id, project_key, 1 if is_subagent else 0),
    )


def _apply_line_result(
    conn: sqlite3.Connection,
    session_id: str,
    result: LineParseResult,
) -> None:
    for event in result.events:
        conn.execute(
            """
            INSERT INTO events (
              session_id, event_type, timestamp, role, git_branch, cwd,
              text, tool_name, tool_input, stderr, is_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                event.event_type,
                event.timestamp,
                event.role,
                event.git_branch,
                event.cwd,
                event.text,
                event.tool_name,
                event.tool_input,
                event.stderr,
                event.is_error,
            ),
        )

    if result.token_usage:
        u = result.token_usage
        conn.execute(
            """
            INSERT INTO token_usage (
              session_id, timestamp, model, input_tokens, output_tokens,
              cache_read_tokens, cache_create_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                u.timestamp,
                u.model,
                u.input_tokens,
                u.output_tokens,
                u.cache_read_tokens,
                u.cache_create_tokens,
            ),
        )

    ts_values = [e.timestamp for e in result.events if e.timestamp]
    cwd = next((e.cwd for e in result.events if e.cwd), None)
    git_branch = next((e.git_branch for e in result.events if e.git_branch), None)
    min_ts = min(ts_values) if ts_values else None
    max_ts = max(ts_values) if ts_values else None

    conn.execute(
        """
        UPDATE sessions SET
          title = COALESCE(?, title),
          slug = COALESCE(?, slug),
          cwd = COALESCE(?, cwd),
          git_branch = COALESCE(?, git_branch),
          started_at = CASE
            WHEN ? IS NULL THEN started_at
            WHEN started_at IS NULL OR started_at > ? THEN ?
            ELSE started_at END,
          ended_at = CASE
            WHEN ? IS NULL THEN ended_at
            WHEN ended_at IS NULL OR ended_at < ? THEN ?
            ELSE ended_at END,
          message_count = message_count + ?
        WHERE session_id = ?
        """,
        (
            result.title,
            result.slug,
            cwd,
            git_branch,
            min_ts,
            min_ts,
            min_ts,
            max_ts,
            max_ts,
            max_ts,
            len(result.events),
            session_id,
        ),
    )


def ingest_file(conn: sqlite3.Connection, path: Path, root: Path) -> int:
    project_key = _project_key(path, root)
    session_id, _, is_subagent = _session_id_from_path(path, project_key)
    _ensure_session(conn, session_id, project_key, is_subagent)

    mtime = path.stat().st_mtime
    row = conn.execute(
        "SELECT file_mtime, byte_offset, line_count FROM ingest_state WHERE file_path = ?",
        (str(path),),
    ).fetchone()

    start_offset = 0
    line_count = 0
    if row and row["file_mtime"] == mtime:
        return 0
    if row and row["file_mtime"] != mtime:
        start_offset = row["byte_offset"] if row["byte_offset"] else 0
        line_count = row["line_count"] or 0

    new_lines = 0
    with open(path, "rb") as fh:
        fh.seek(start_offset)
        while True:
            offset_before = fh.tell()
            line_bytes = fh.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace")
            result = parse_jsonl_line(line)
            if result:
                _apply_line_result(conn, session_id, result)
                new_lines += 1

        end_offset = fh.tell()

    conn.execute(
        """
        INSERT INTO ingest_state (file_path, file_mtime, byte_offset, line_count, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
          file_mtime = excluded.file_mtime,
          byte_offset = excluded.byte_offset,
          line_count = excluded.line_count,
          updated_at = excluded.updated_at
        """,
        (str(path), mtime, end_offset, line_count + new_lines, _utc_now()),
    )
    return new_lines


def ingest_all(
    *,
    root: Path | None = None,
    include_subagents: bool = False,
    force: bool = False,
    db: Path | None = None,
) -> dict:
    conn = ensure_db(db)
    base = root or projects_dir()

    if force:
        conn.execute("DELETE FROM ingest_state")
        conn.commit()

    files = discover_jsonl_files(base, include_subagents=include_subagents)
    total_lines = 0
    changed_files = 0

    for path in files:
        before = conn.execute(
            "SELECT 1 FROM ingest_state WHERE file_path = ?", (str(path),)
        ).fetchone()
        lines = ingest_file(conn, path, base)
        if lines > 0 or not before:
            changed_files += 1
        total_lines += lines

    conn.commit()
    pending = _count_pending_files(conn, base, include_subagents)
    return {
        "files_scanned": len(files),
        "files_updated": changed_files,
        "lines_ingested": total_lines,
        "pending_files": pending,
    }


def reindex(
    *,
    root: Path | None = None,
    include_subagents: bool = False,
    db: Path | None = None,
) -> dict:
    conn = ensure_db(db)
    conn.executescript(
        """
        DELETE FROM events;
        DELETE FROM token_usage;
        DELETE FROM session_metrics;
        DELETE FROM plan_sessions;
        DELETE FROM plans;
        DELETE FROM sessions;
        DELETE FROM ingest_state;
        """
    )
    conn.commit()
    return ingest_all(
        root=root,
        include_subagents=include_subagents,
        force=False,
        db=db,
    )


def _count_pending_files(
    conn: sqlite3.Connection,
    root: Path,
    include_subagents: bool,
) -> int:
    files = discover_jsonl_files(root, include_subagents=include_subagents)
    pending = 0
    for path in files:
        mtime = path.stat().st_mtime
        row = conn.execute(
            "SELECT file_mtime FROM ingest_state WHERE file_path = ?",
            (str(path),),
        ).fetchone()
        if not row or row["file_mtime"] != mtime:
            pending += 1
    return pending
