# Retroscope — Claude Code session analysis

Structured work reports from Claude Code session history. Offline by default (no API keys).

Inspired by GitHub Copilot CLI `/chronicle`, but reads Claude Code's native JSONL logs and builds a local SQLite index at `~/.retroscope/store.db`.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.12+

## Installation (plugin)

From this repo:

```bash
/plugin marketplace add ./.claude-plugin
/plugin install retroscope@retroscope
```

Or standalone CLI:

```bash
uv run --script retroscope.py standup
uv run --script retroscope.py search "auth"
uv run --script retroscope.py tips
uv run --script retroscope.py tips --since 7d --focus skills
uv run --script retroscope.py cost-tips
uv run --script retroscope.py cost-tips --since 7d
uv run --script retroscope.py status
uv run --script retroscope.py reindex
```

## Skills

| Skill | Purpose |
|-------|---------|
| `/retroscope-standup` | Work recap (default: past 24h) |
| `/retroscope-search` | Keyword search across sessions |
| `/retroscope-tips` | Workflow improvement tips |
| `/retroscope-cost-tips` | Token cost analysis and tips |

## Data sources

- **Primary:** `~/.claude/projects/**/*.jsonl`
- **Index cache:** `~/.retroscope/store.db` (override with `RETROSCOPE_DATA_DIR`)

Subagent logs are excluded by default. Use `--include-subagents` to include them.

## Privacy

Phase 1 is fully offline. Future `--llm` modes may send aggregated summaries to an external API — not implemented yet.

## Phase status

- ✅ Phase 1: JSONL ingest, standup, search, reindex, status, MCP plugin
- ⏳ Phase 1.5: Desktop `local_*.json` index join
- ✅ Phase 2: token_usage 集計, session_metrics, tips, cost-tips, FTS5 検索
- ⏳ Phase 3+: improve, `--llm`

See [claude-retroscope.md](./claude-retroscope.md) for the full design doc.
