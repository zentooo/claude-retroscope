# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

"""Retroscope CLI — analyze Claude Code session history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from cost import format_cost_tips  # noqa: E402
from ingest import ingest_all, reindex  # noqa: E402
from paths import db_path, format_path, projects_dir  # noqa: E402
from search_fmt import format_search  # noqa: E402
from standup import format_standup  # noqa: E402
from store import db_stats, ensure_db  # noqa: E402
from tips import format_tips  # noqa: E402


def cmd_standup(args: argparse.Namespace) -> int:
    conn = ensure_db()
    ingest_all(include_subagents=args.include_subagents)
    conn = ensure_db()
    print(format_standup(conn, since=args.since))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    conn = ensure_db()
    ingest_all(include_subagents=args.include_subagents)
    conn = ensure_db()
    print(format_search(conn, args.query, limit=args.limit, project=args.project))
    return 0


def cmd_tips(args: argparse.Namespace) -> int:
    conn = ensure_db()
    ingest_all(include_subagents=args.include_subagents)
    conn = ensure_db()
    print(format_tips(conn, since=args.since, focus=args.focus))
    return 0


def cmd_cost_tips(args: argparse.Namespace) -> int:
    conn = ensure_db()
    ingest_all(include_subagents=args.include_subagents)
    conn = ensure_db()
    print(
        format_cost_tips(
            conn,
            since=args.since,
            focus=args.focus,
            include_subagents=args.include_subagents,
        )
    )
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    stats = reindex(include_subagents=args.include_subagents)
    print(
        f"Reindexed {stats['files_scanned']} files "
        f"({stats['lines_ingested']} new lines)"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    conn = ensure_db()
    stats = db_stats(conn)
    db = db_path()
    size_mb = db.stat().st_size / (1024 * 1024) if db.exists() else 0
    pending = ingest_all(include_subagents=args.include_subagents)["pending_files"]

    print("=== Retroscope Status ===")
    print(f"Projects dir: {format_path(projects_dir())}")
    print(f"Index DB:     {format_path(db)} ({size_mb:.2f} MB)")
    print(f"Sessions:     {stats['sessions']}")
    print(f"Events:       {stats['events']}")
    print(f"Token rows:   {stats['token_rows']}")
    print(f"Metrics:      {stats['metrics_rows']}")
    print(f"FTS indexed:  {stats['fts_rows']}")
    print(f"Ingested:     {stats['ingested_files']} files")
    print(f"Last ingest:  {stats['last_ingest_at'] or 'never'}")
    print(f"Pending:      {pending} files need ingest")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="retroscope",
        description="Analyze Claude Code session history (offline by default).",
    )
    parser.add_argument(
        "--include-subagents",
        action="store_true",
        help="Include subagent JSONL logs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_standup = sub.add_parser("standup", help="Work recap for a time period")
    p_standup.add_argument(
        "--since",
        default=None,
        help="Period: 24h (default), 3d, 7d, or ISO date",
    )
    p_standup.set_defaults(func=cmd_standup)

    p_search = sub.add_parser("search", help="Search session contents")
    p_search.add_argument("query", help="Search keywords")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.add_argument("--project", help="Filter by project path or key")
    p_search.set_defaults(func=cmd_search)

    p_tips = sub.add_parser("tips", help="Workflow improvement tips")
    p_tips.add_argument(
        "--since",
        default=None,
        help="Period: 24h (default), 3d, 7d, or ISO date",
    )
    p_tips.add_argument(
        "--focus",
        choices=["prompting", "skills", "sessions", "planning"],
        help="Limit tips to a category",
    )
    p_tips.set_defaults(func=cmd_tips)

    p_cost = sub.add_parser("cost-tips", help="Token cost analysis and tips")
    p_cost.add_argument(
        "--since",
        default=None,
        help="Period: 24h (default), 3d, 7d, or ISO date",
    )
    p_cost.add_argument(
        "--focus",
        choices=["cache", "sessions", "skills", "subagents"],
        help="Limit tips to a category",
    )
    p_cost.set_defaults(func=cmd_cost_tips)

    sub.add_parser("reindex", help="Rebuild index from JSONL").set_defaults(
        func=cmd_reindex
    )

    sub.add_parser("status", help="Show index status").set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
