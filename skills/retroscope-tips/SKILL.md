---
name: retroscope-tips
description: Workflow improvement tips grounded in Anthropic's official Claude Code best practices.
argument-hint: [--since 24h|3d|7d] [--focus prompting|skills|sessions|planning]
allowed-tools: mcp__plugin_retroscope_retroscope__*
---

# Retroscope Tips

Analyze indexed Claude Code sessions for workflow improvement opportunities.

## Instructions

1. Call `mcp__plugin_retroscope_retroscope__retroscope_tips` with an appropriate `since` period:
   - Default daily review → `since="24h"`
   - Weekly review → `since="7d"`
   - User-specified → pass through (e.g. `3d`, `2026-05-28`)
2. Use `focus` when the user asks about a specific area:
   - prompting / corrections / paste → `focus="prompting"`
   - SKILL.md re-reads → `focus="skills"`
   - short session churn → `focus="sessions"`
   - plan mode → `focus="planning"`
3. Present tips by severity. Each tip includes the official Anthropic recommendation and a source link — relay these to the user verbatim.
4. If no data, suggest `retroscope_reindex`.

Default is **offline** — grounded in [Anthropic Claude Code best practices](https://code.claude.com/docs/en/best-practices).
