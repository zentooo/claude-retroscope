"""SQLite store for Retroscope index."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from paths import db_path, schema_path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db: Path | None = None) -> sqlite3.Connection:
    target = db or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    sql = schema_path().read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def ensure_db(db: Path | None = None) -> sqlite3.Connection:
    conn = connect(db)
    init_db(conn)
    return conn


def db_stats(conn: sqlite3.Connection) -> dict:
    sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    ingested = conn.execute("SELECT COUNT(*) FROM ingest_state").fetchone()[0]
    last = conn.execute(
        "SELECT MAX(updated_at) FROM ingest_state"
    ).fetchone()[0]
    return {
        "sessions": sessions,
        "events": events,
        "ingested_files": ingested,
        "last_ingest_at": last,
    }
