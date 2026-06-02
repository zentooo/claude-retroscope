# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Retroscope analyzes Claude Code session history (the native JSONL logs under `~/.claude/projects/**/*.jsonl`) and produces standup reports, full-text search, workflow tips, and token-cost analysis. It runs **fully offline** — no API calls, no external services. State lives in a local SQLite index at `~/.retroscope/store.db`.

It ships two surfaces over the same core logic:
- **CLI** — `retroscope.py` (argparse subcommands)
- **MCP plugin** — `server.py` (FastMCP tools), installed as a Claude Code plugin via `.claude-plugin/` + `skills/`

## Commands

```bash
# Run tests (no pyproject.toml — do NOT use `uv run pytest`, it tries to build a package and fails)
.venv/bin/pytest -q

# Run the CLI standalone (PEP 723 inline-script deps, run via uv)
uv run --script retroscope.py reindex      # build/refresh index — required once before first standalone use
uv run --script retroscope.py standup --since 7d
uv run --script retroscope.py search "auth"
uv run --script retroscope.py tips --focus prompting
uv run --script retroscope.py cost-tips --focus cache
uv run --script retroscope.py improve --since 7d --stable-days 7
uv run --script retroscope.py status

# Run the MCP server (stdio); the only dependency beyond stdlib is `mcp>=1.0`
uv run --script server.py
```

Both entrypoints carry a `# /// script` PEP 723 header declaring dependencies; there is no requirements file or lockfile. Tests have no external deps and run against `.venv/bin/pytest`.

## Architecture

All real logic lives in `scripts/`. `retroscope.py` and `server.py` are thin adapters that both `sys.path.insert` the `scripts/` dir and call the same functions, so **CLI subcommands and MCP tools must stay behaviorally identical** — when you change one surface, mirror it in the other.

Data flow: `JSONL logs → parser → ingest → SQLite → queries → formatters → output`

- **`paths.py`** — OS-aware locations. `~/.claude/projects` for source logs, `~/.retroscope/store.db` for the index (override via `RETROSCOPE_DATA_DIR`). `desktop_session_roots()` is the Phase 1.5 stub for Desktop `local_*.json` (not yet wired in).
- **`parser.py`** — turns one raw JSONL line into a `LineParseResult` (normalized events + token-usage rows). Only `user`/`assistant` line types are known; unknown types warn. This is where Claude Code's log shape is interpreted.
- **`ingest.py`** — **incremental** ingest. `ingest_state` tracks per-file `(mtime, byte_offset, line_count)`, so re-ingesting only reads appended bytes. `ingest_all()` does a cheap diff-load and is called at the top of nearly every command/tool so output is always fresh; `reindex()` rebuilds from scratch. Subagent logs (`subagents/` dir or `agent-*` stem) are excluded unless `include_subagents=True`. Session metrics are recomputed when stale.
- **`store.py`** — connection + `ensure_db()` (applies `store/schema.sql` idempotently) + `db_stats()`.
- **`store/schema.sql`** — the index schema: `sessions`, `events`, `token_usage`, `session_metrics`, an FTS5 virtual table `events_fts` (Phase 2 full-text search, `unicode61` tokenizer), plus `plans`/`plan_sessions` and `ingest_state`. Schema is applied with `executescript` on every connect, so all DDL must stay `IF NOT EXISTS`.
- **`queries.py`** — all SQL reads: period parsing (`24h`/`3d`/`7d`/ISO), `sessions_in_period`, FTS search with a LIKE fallback when FTS is unavailable, token/tool aggregations, bash-heavy / agent-heavy session detection.
- **`metrics.py`** — derives `session_metrics` (turns, tool calls, skill re-reads, corrections, etc.) used by tips/cost-tips.
- **`guidelines.py`** — static catalog of Anthropic best-practice rules + doc links that `tips.py` matches observed patterns against.
- **`improve.py`** — friction-signal analysis. Detects recurring build/test errors (`is_error` events grouped by a normalized signature) and repeated user course-corrections (reuses `metrics.CORRECTION_PATTERNS` + best-effort "use X not Y" directive extraction), grouped by project `cwd`, then maps each to a candidate `CLAUDE.md` rule. Offline and **report-only** — never writes files. `--stable-days N` excludes the most recent N days to skip incident-response noise.
- **`cost.py` / `tips.py` / `standup.py` / `search_fmt.py` / `improve.py`** — formatters. They take a connection and return the final human-readable string; the CLI and MCP layers just `print`/return it.

## Plugin packaging

- `.claude-plugin/plugin.json` declares the `retroscope` MCP server (`uv run --script ${CLAUDE_PLUGIN_ROOT}/server.py`). MCP config lives here, **not** in a separate project config, to avoid double-loading.
- `.claude-plugin/marketplace.json` is the marketplace manifest.
- `skills/*/SKILL.md` define the slash commands (`/retroscope-standup`, `-search`, `-tips`, `-cost-tips`, `-improve`, `-reindex`). They are instruction files that call the `mcp__plugin_retroscope_retroscope__*` tools — keep their argument contract in sync with `server.py` tool signatures.
- Bump the `version` in **both** `plugin.json` and `marketplace.json` together.

## Conventions

- Python 3.12+, `from __future__ import annotations`, modern type hints (`X | None`), dataclasses for parsed records.
- `scripts/` modules import each other by bare name (e.g. `from parser import ...`), relying on the `sys.path.insert`. Keep that pattern — don't convert to package-relative imports.
- Default is always offline / CLI logs only; `--include-subagents` is the explicit opt-in everywhere it appears.
- Tests use `monkeypatch` to redirect `projects_dir` and set `RETROSCOPE_DATA_DIR` to a tmp dir, then ingest `tests/fixtures/sample.jsonl`. Follow that pattern for new ingest/query tests rather than touching the real `~/.claude` or `~/.retroscope`.

Phase roadmap: Phase 1/2 done; Phase 3 `improve` shipped as offline report-only friction analysis. Phase 1.5 Desktop index merge and Phase 3 `--apply` (write rules to CLAUDE.md) / `--llm` rule synthesis still pending.
