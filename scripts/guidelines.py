"""Official Anthropic Claude Code guideline catalog.

Source: https://code.claude.com/docs/en/best-practices
"""

from __future__ import annotations

from dataclasses import dataclass

_BASE = "https://code.claude.com/docs/en/best-practices"


@dataclass(frozen=True)
class Guideline:
    id: str
    category: str
    title: str
    recommendation: str
    detail: str
    source_url: str
    default_severity: str  # high | medium | low


CATALOG: dict[str, Guideline] = {g.id: g for g in [
    Guideline(
        id="specific-prompts",
        category="prompting",
        title="Provide specific context in your prompts",
        recommendation=(
            "The more precise your instructions, the fewer corrections you'll need. "
            "Reference specific files, mention constraints, and point to example patterns."
        ),
        detail=(
            "Scope the task (which file, scenario, testing preferences), "
            "point to sources (git history, existing patterns), "
            "and describe the symptom with location and what 'fixed' looks like. "
            "After two failed corrections, use /clear and write a better initial prompt "
            "incorporating what you learned."
        ),
        source_url=f"{_BASE}#provide-specific-context-in-your-prompts",
        default_severity="high",
    ),
    Guideline(
        id="file-reference",
        category="prompting",
        title="Reference files with @ instead of pasting",
        recommendation=(
            "Use @ to reference files, paste screenshots/images, or pipe data directly. "
            "Reference files with @ instead of describing where code lives — "
            "Claude reads the file before responding."
        ),
        detail=(
            "Paste images directly (copy/paste or drag-and-drop). "
            "Pipe in data with `cat error.log | claude`. "
            "Large inline pastes consume context quickly and may truncate important content."
        ),
        source_url=f"{_BASE}#provide-rich-content",
        default_severity="medium",
    ),
    Guideline(
        id="plan-mode",
        category="planning",
        title="Explore first, then plan, then code",
        recommendation=(
            "Use plan mode to separate exploration from execution. "
            "Planning is most useful when you're uncertain about the approach, "
            "when the change modifies multiple files, or when you're unfamiliar "
            "with the code being modified."
        ),
        detail=(
            "Recommended workflow: (1) Explore in plan mode — Claude reads files without changes. "
            "(2) Plan — ask for a detailed implementation plan. "
            "(3) Implement — switch out of plan mode and let Claude code. "
            "(4) Commit. "
            "If you could describe the diff in one sentence, skip the plan."
        ),
        source_url=f"{_BASE}#explore-first-then-plan-then-code",
        default_severity="low",
    ),
    Guideline(
        id="resume-sessions",
        category="sessions",
        title="Resume conversations instead of starting fresh",
        recommendation=(
            "Claude Code saves conversations locally. "
            "Run `claude --continue` to pick up the most recent session, "
            "or `claude --resume` to choose from a list. "
            "Give sessions descriptive names with /rename so you can find them later."
        ),
        detail=(
            "Treat sessions like branches: each workstream gets its own persistent context. "
            "Starting a fresh session re-reads all the same files and re-explains context, "
            "consuming tokens unnecessarily."
        ),
        source_url=f"{_BASE}#resume-conversations",
        default_severity="medium",
    ),
    Guideline(
        id="clear-between-tasks",
        category="sessions",
        title="Run /clear between unrelated tasks",
        recommendation=(
            "Use /clear frequently between tasks to reset the context window entirely. "
            "Long sessions with irrelevant context can reduce performance and distract Claude."
        ),
        detail=(
            "The kitchen sink session: starting with one task then asking something unrelated "
            "fills context with irrelevant information. "
            "Context is the most important resource to manage — "
            "LLM performance degrades as the context window fills."
        ),
        source_url=f"{_BASE}#manage-context-aggressively",
        default_severity="medium",
    ),
    Guideline(
        id="skills-on-demand",
        category="skills",
        title="Use skills for domain knowledge instead of repeating context",
        recommendation=(
            "For domain knowledge or workflows that are only relevant sometimes, "
            "use skills instead of CLAUDE.md. "
            "Claude loads them on demand without bloating every conversation."
        ),
        detail=(
            "Create SKILL.md files in .claude/skills/ for reusable workflows. "
            "Invoke with /skill-name or let Claude apply them automatically. "
            "Repeated reads of the same SKILL.md within a session suggest "
            "the skill should be referenced upfront in the prompt."
        ),
        source_url=f"{_BASE}#create-skills",
        default_severity="high",
    ),
    Guideline(
        id="verification",
        category="verification",
        title="Give Claude a way to verify its work",
        recommendation=(
            "Give Claude a check it can run: tests, a build, a screenshot to compare. "
            "It's the difference between a session you watch and one you walk away from."
        ),
        detail=(
            "The check is anything that returns a signal Claude can read: "
            "a test suite, a build exit code, a linter, or a diff script. "
            "Have Claude show evidence rather than asserting success: "
            "the test output, the command it ran and what it returned."
        ),
        source_url=f"{_BASE}#give-claude-a-way-to-verify-its-work",
        default_severity="high",
    ),
    Guideline(
        id="claude-md-concise",
        category="prompting",
        title="Keep CLAUDE.md concise — long files cause Claude to ignore rules",
        recommendation=(
            "If your CLAUDE.md is too long, Claude ignores half of it because important rules "
            "get lost in the noise. Ruthlessly prune. "
            "If Claude already does something correctly without the instruction, delete it."
        ),
        detail=(
            "For each line ask: 'Would removing this cause Claude to make mistakes?' "
            "If not, cut it. Convert stable rules to hooks for deterministic enforcement. "
            "CLAUDE.md is loaded every session — only include things that apply broadly."
        ),
        source_url=f"{_BASE}#write-an-effective-claudemd",
        default_severity="medium",
    ),
    Guideline(
        id="subagents-investigation",
        category="sessions",
        title="Use subagents for investigation to keep main context clean",
        recommendation=(
            "Delegate research with 'use subagents to investigate X'. "
            "They explore in a separate context, keeping your main conversation "
            "clean for implementation."
        ),
        detail=(
            "When Claude researches a codebase it reads lots of files, "
            "all of which consume your context. "
            "Subagents run in separate context windows and report back summaries. "
            "The infinite exploration failure: asking Claude to 'investigate' without scoping "
            "causes it to read hundreds of files, filling the context."
        ),
        source_url=f"{_BASE}#use-subagents-for-investigation",
        default_severity="medium",
    ),
    Guideline(
        id="bash-over-read",
        category="tools",
        title="Use Read/Edit instead of Bash for file operations",
        recommendation=(
            "Prefer the Read tool over `cat`/`head`/`tail` in Bash, "
            "and Edit/Write over `sed`/`awk`. "
            "Dedicated file tools produce cleaner diffs and consume fewer context tokens."
        ),
        detail=(
            "Bash commands like `cat file` return raw file content as tool output, "
            "which is included verbatim in the context window. "
            "The Read tool renders the same content more compactly and lets Claude "
            "reference line numbers without re-reading. "
            "High Bash ratios with file-read patterns are a signal to switch tools."
        ),
        source_url=f"{_BASE}#use-the-right-tools",
        default_severity="medium",
    ),
    Guideline(
        id="agent-tool-cost",
        category="tools",
        title="Each Agent tool call spawns a new context — scope them narrowly",
        recommendation=(
            "Tell Agent calls exactly what to look for and where. "
            "Many broad Agent calls multiply token cost: each spawns its own context window "
            "that re-reads shared files independently."
        ),
        detail=(
            "Agent tool calls are additive: N agents = N independent context windows. "
            "A session with 10+ Agent calls is likely re-reading the same files repeatedly. "
            "Prefer targeted queries ('look only in src/auth/') over open-ended ones, "
            "or consolidate multiple investigations into one scoped subagent."
        ),
        source_url=f"{_BASE}#use-subagents-for-investigation",
        default_severity="medium",
    ),
    Guideline(
        id="compact-context",
        category="cost",
        title="Use /compact to reduce cache creation mid-session",
        recommendation=(
            "Run `/compact` to compress conversation history mid-session without losing progress. "
            "For more control, run `/compact <instructions>` like "
            "`/compact Focus on the API changes` to guide what gets preserved."
        ),
        detail=(
            "Cache creation tokens are billed at write-time and recur every time the context grows. "
            "High cache_create ratio means you're paying to cache content that could be summarized away. "
            "Auto compaction triggers near context limits; run /compact proactively to stay ahead of it. "
            "Customize what survives in CLAUDE.md: "
            "'When compacting, always preserve the full list of modified files and any test commands.'"
        ),
        source_url=f"{_BASE}#manage-context-aggressively",
        default_severity="high",
    ),
    Guideline(
        id="session-length",
        category="cost",
        title="Split long sessions to reduce cumulative token cost",
        recommendation=(
            "Use `/clear` between unrelated tasks, or start a new session for each distinct workstream. "
            "Resume with `claude --continue` or `claude --resume` instead of re-pasting context."
        ),
        detail=(
            "Context is the most important resource to manage — LLM performance degrades as it fills, "
            "and every turn in a long session carries the full accumulated context as input cost. "
            "A session with 15+ turns and 200k+ input tokens is a signal to split: "
            "finish the current task, commit, then start fresh for the next one."
        ),
        source_url=f"{_BASE}#manage-context-aggressively",
        default_severity="medium",
    ),
    Guideline(
        id="encode-corrections",
        category="instructions",
        title="Encode recurring corrections into CLAUDE.md",
        recommendation=(
            "When you correct Claude the same way across sessions, promote that correction "
            "into CLAUDE.md (or a rule file) so it becomes a standing instruction instead of "
            "something you re-explain every time."
        ),
        detail=(
            "Repeated course-corrections in the same project are the clearest signal that a piece "
            "of project knowledge is missing from your instructions. Capture the rule once — "
            "e.g. 'This project uses vitest, never jest' — so it isn't rediscovered each session. "
            "Keep each rule short and imperative so it survives CLAUDE.md pruning."
        ),
        source_url=f"{_BASE}#write-an-effective-claudemd",
        default_severity="high",
    ),
    Guideline(
        id="document-recurring-errors",
        category="instructions",
        title="Document recurring build/test failures and their fixes",
        recommendation=(
            "If the same build or test error keeps recurring across sessions, add a short note to "
            "CLAUDE.md describing the trigger and the fix so Claude avoids reintroducing it."
        ),
        detail=(
            "A failure that shows up repeatedly is environment- or convention-specific knowledge "
            "that isn't written down yet. Record the trigger and the resolution "
            "(e.g. 'Run `uv run --script`, not `python` — deps are PEP 723 inline') "
            "so the same dead-end isn't rediscovered each session."
        ),
        source_url=f"{_BASE}#give-claude-a-way-to-verify-its-work",
        default_severity="medium",
    ),
    Guideline(
        id="subagent-scope",
        category="cost",
        title="Scope subagents narrowly to avoid runaway token usage",
        recommendation=(
            "Tell subagents exactly what files or directories to explore. "
            "The infinite exploration failure: asking Claude to 'investigate' without scoping "
            "causes it to read hundreds of files, multiplying cost across parallel contexts."
        ),
        detail=(
            "Subagents run in their own context windows, so their token usage is additive. "
            "A broadly-scoped research subagent can consume as much as the main session. "
            "Prefer: 'use a subagent to check only src/auth/ for token refresh handling' "
            "over: 'use a subagent to investigate authentication'."
        ),
        source_url=f"{_BASE}#use-subagents-for-investigation",
        default_severity="low",
    ),
]}


def get(guideline_id: str) -> Guideline:
    return CATALOG[guideline_id]
