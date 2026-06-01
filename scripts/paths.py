"""OS-aware path resolution for Claude Code data sources."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def claude_home() -> Path:
    return Path.home() / ".claude"


def projects_dir() -> Path:
    return claude_home() / "projects"


def data_dir() -> Path:
    override = os.environ.get("RETROSCOPE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".retroscope"


def db_path() -> Path:
    return data_dir() / "store.db"


def schema_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    return root / "store" / "schema.sql"


def desktop_session_roots() -> list[Path]:
    """Desktop index directories (Phase 1.5). Empty on unsupported platforms."""
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "Claude"
        return [
            base / "claude-code-sessions",
            base / "local-agent-mode-sessions",
        ]
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return []
        base = Path(appdata) / "Claude"
        return [
            base / "claude-code-sessions",
            base / "local-agent-mode-sessions",
        ]
    return []


def format_path(path: str | Path | None) -> str:
    if not path:
        return "unknown"
    text = str(path)
    home = str(Path.home())
    if text.startswith(home):
        return "~" + text[len(home) :]
    return text
