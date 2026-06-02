---
name: retroscope-reindex
description: Rebuild the Retroscope index from Claude Code JSONL logs (use after migrating machines or if the index looks stale or corrupt).
argument-hint: [--include-subagents]
allowed-tools: mcp__plugin_retroscope_retroscope__*
---

# Retroscope Reindex

Rebuild the local Retroscope index from scratch by re-reading all Claude Code
JSONL logs under `~/.claude/projects/`.

## Instructions

1. Normally the index refreshes incrementally on every command — you do **not**
   need to reindex routinely. Reach for this only when:
   - results look stale or empty despite known activity
   - you migrated to a new machine or restored logs
   - the index DB may be corrupt
2. Call `mcp__plugin_retroscope_retroscope__retroscope_reindex`.
   - Set `include_subagents=True` only if the user wants subagent logs indexed too.
3. Report the result (files scanned / lines ingested) back to the user.
4. If you only want to check freshness without rebuilding, use
   `mcp__plugin_retroscope_retroscope__retroscope_status` instead.

Default is **offline** — reads local JSONL only.
