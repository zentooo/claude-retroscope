"""Search result formatting."""

from __future__ import annotations

import shlex
import sqlite3

from paths import format_path
from queries import search_events


def format_search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 20,
    project: str | None = None,
) -> str:
    results = search_events(conn, query, limit=limit, project=project)
    if not results:
        return f'No sessions found matching "{query}"'

    lines = [f'=== Sessions matching "{query}" ===', ""]
    for i, r in enumerate(results, 1):
        cwd_display = format_path(r["cwd"])
        lines.append(f"[{i}] {cwd_display}")
        if r["title"]:
            lines.append(f"    {r['title']}")
        if r["cwd"]:
            needs_quote = not cwd_display.startswith("~")
            quoted = shlex.quote(cwd_display) if needs_quote else cwd_display
            lines.append(f"    cd {quoted} && claude --resume {r['session_id']}")
        else:
            lines.append(f"    claude --resume {r['session_id']}")
        for role, snippet in r["matches"]:
            prefix = {"user": "❯", "summary": "·", "system": "%"}.get(role, " ")
            lines.append(f"    {prefix} {snippet}")
        lines.append("")

    return "\n".join(lines).rstrip()
