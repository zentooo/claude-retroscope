---
name: retroscope-search
description: Search past Claude Code session contents by keyword across all projects.
argument-hint: [keywords...]
allowed-tools: mcp__plugin_retroscope_retroscope__*
---

# Retroscope Search

Deep search across indexed Claude Code session logs.

## Arguments

If `$ARGUMENTS` is non-empty, join tokens into the search query.

## Instructions

1. Call `mcp__plugin_retroscope_retroscope__retroscope_search` with the keyword query.
2. Use `project` filter when the user scopes to a specific repo.
3. Present matches with resume commands (`cd ... && claude --resume <id>`).
4. For domain terms with alternate spellings (EN/JA), run multiple searches and merge results.

Default is **offline** — searches the local SQLite index only.
