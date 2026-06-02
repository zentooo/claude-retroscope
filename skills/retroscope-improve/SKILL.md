---
name: retroscope-improve
description: Suggest CLAUDE.md rules from recurring friction (errors and repeated corrections) in past Claude Code sessions.
argument-hint: [--since 7d|24h|3d] [--stable-days N] [--focus errors|corrections] [--project PATH]
allowed-tools: mcp__plugin_retroscope_retroscope__*
---

# Retroscope Improve

Surface recurring friction in past sessions and propose project-instruction
(`CLAUDE.md`) rules that would prevent it from recurring. Inspired by Copilot
CLI's `/chronicle improve`, but reads Claude Code's local JSONL index.

## Instructions

1. Call `mcp__plugin_retroscope_retroscope__retroscope_improve` with an appropriate `since` period:
   - Default → `since="7d"` (improve needs more data than a daily recap)
   - Wider review → `since="14d"` / `30d`
   - User-specified → pass through
2. Recurring incidents skew the signal. When the user wants steady-state
   knowledge (not a recent firefight), pass `stable_days` to exclude the most
   recent days, e.g. `stable_days=7`.
3. Use `focus` when scoped:
   - recurring build/test errors → `focus="errors"`
   - repeated user course-corrections → `focus="corrections"`
4. Use `project` to scope to one repo by path or project key.
5. Present the suggestions grouped by project, with the target `CLAUDE.md` path.
   Make clear the suggestions are **heuristic** — the user should review and
   edit before adding any rule. Nothing is written automatically.

Default is **offline** — no external API calls. Suggestions come from the local index only.
