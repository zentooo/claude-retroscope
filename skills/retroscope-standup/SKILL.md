---
name: retroscope-standup
description: Generate a structured work recap from Claude Code sessions (standup / daily recap).
argument-hint: [--since 24h|3d|7d]
allowed-tools: mcp__plugin_retroscope_retroscope__*
---

# Retroscope Standup

Generate a work recap from indexed Claude Code sessions.

## Instructions

1. Call `mcp__plugin_retroscope_retroscope__retroscope_standup` with an appropriate `since` period:
   - "yesterday" / daily → `since="24h"` (default)
   - "this week" / weekly → `since="7d"`
   - User-specified → pass through (e.g. `3d`, `2026-05-28`)
2. Present the tool output to the user, grouped by project.
3. Highlight in-progress sessions and include resume commands verbatim.
4. If the index looks empty, suggest running `retroscope reindex` or the MCP `retroscope_reindex` tool.

Default is **offline** — no external API calls.
