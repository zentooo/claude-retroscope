---
name: retroscope-cost-tips
description: Token cost analysis and cost-reduction tips from Claude Code session usage.
argument-hint: [--since 24h|3d|7d] [--focus cache|sessions|skills|subagents]
allowed-tools: mcp__plugin_retroscope_retroscope__*
---

# Retroscope Cost Tips

Analyze token usage patterns and suggest cost-reduction strategies.

## Instructions

1. Call `mcp__plugin_retroscope_retroscope__retroscope_cost_tips` with an appropriate `since` period:
   - Default → `since="24h"`
   - Weekly review → `since="7d"`
   - User-specified → pass through
2. Use `focus` when scoped:
   - cache creation / `/compact` → `focus="cache"`
   - long sessions → `focus="sessions"`
   - skill re-reads → `focus="skills"`
   - subagent cost → `focus="subagents"` (also set `include_subagents=True`)
3. Present the daily token table and top sessions, then actionable recommendations.
4. If token rows are zero, suggest `retroscope_reindex` to rebuild the index with usage data.

Default is **offline** — reads local `token_usage` index only.
