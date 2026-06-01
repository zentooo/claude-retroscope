"""JSONL parser — Claude Code session logs to normalized events."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

KNOWN_TYPES = frozenset(
    {
        "user",
        "assistant",
        "summary",
        "system",
        "attachment",
        "ai-title",
        "file-history-snapshot",
        "mode",
        "permission-mode",
        # Observed metadata types — intentionally not indexed
        "last-prompt",
        "queue-operation",
        "pr-link",
        "agent-name",
    }
)

ROLE_WEIGHT = {"user": 3, "summary": 3, "assistant": 1, "system": 1}


@dataclass
class NormalizedEvent:
    event_type: str
    role: str | None
    timestamp: str | None
    git_branch: str | None
    cwd: str | None
    text: str | None
    tool_name: str | None = None
    tool_input: str | None = None
    stderr: str | None = None
    is_error: int = 0


@dataclass
class TokenUsageRow:
    timestamp: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_create_tokens: int | None


@dataclass
class LineParseResult:
    events: list[NormalizedEvent] = field(default_factory=list)
    title: str | None = None
    slug: str | None = None
    token_usage: TokenUsageRow | None = None
    unknown_type: str | None = None


def _extract_content_parts(msg: dict[str, Any], role: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Return text parts and (tool_name, tool_input_json) pairs."""
    texts: list[str] = []
    tools: list[tuple[str, str]] = []
    content = msg.get("content", "")

    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            pt = part.get("type")
            if pt == "text":
                t = part.get("text", "")
                if isinstance(t, str) and t.strip():
                    texts.append(t)
            elif pt == "tool_use" and role == "assistant":
                name = part.get("name", "")
                inp = part.get("input", {})
                if isinstance(inp, dict):
                    tools.append((name, json.dumps(inp, ensure_ascii=False)))
                else:
                    tools.append((name, str(inp)))
            elif pt == "thinking":
                t = part.get("thinking", "")
                if isinstance(t, str) and t.strip():
                    texts.append(t)
    elif isinstance(content, str) and content.strip():
        texts.append(content)

    return texts, tools


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def parse_line(raw: dict[str, Any], *, warn_unknown: bool = True) -> LineParseResult:
    result = LineParseResult()
    record_type = raw.get("type")

    if record_type not in KNOWN_TYPES:
        if warn_unknown and record_type:
            result.unknown_type = str(record_type)
        return result

    ts = raw.get("timestamp")
    git_branch = raw.get("gitBranch")
    cwd = raw.get("cwd")
    slug = raw.get("slug")
    if isinstance(slug, str) and slug:
        result.slug = slug

    if record_type == "ai-title":
        title = raw.get("aiTitle")
        if isinstance(title, str) and title.strip():
            result.title = title.strip()
        return result

    if record_type == "summary":
        summary = raw.get("summary", "")
        if isinstance(summary, str) and summary.strip():
            result.title = summary.strip()
            result.events.append(
                NormalizedEvent(
                    event_type="summary",
                    role="summary",
                    timestamp=ts,
                    git_branch=git_branch,
                    cwd=cwd,
                    text=_normalize_text(summary),
                )
            )
        return result

    if record_type == "system":
        content = raw.get("content", "")
        if isinstance(content, str) and content.strip():
            result.events.append(
                NormalizedEvent(
                    event_type="system",
                    role="system",
                    timestamp=ts,
                    git_branch=git_branch,
                    cwd=cwd,
                    text=_normalize_text(content),
                )
            )
        return result

    if record_type in ("mode", "permission-mode", "file-history-snapshot", "attachment"):
        return result

    if record_type in ("user", "assistant"):
        msg = raw.get("message", {})
        if not isinstance(msg, dict):
            return result

        texts, tools = _extract_content_parts(msg, record_type)
        stderr = None
        is_error = 0

        if record_type == "user":
            tur = raw.get("toolUseResult")
            if isinstance(tur, dict):
                for key in ("stdout", "stderr"):
                    v = tur.get(key)
                    if isinstance(v, str) and v.strip():
                        texts.append(v)
                stderr_val = tur.get("stderr")
                if isinstance(stderr_val, str) and stderr_val.strip():
                    stderr = stderr_val
                if tur.get("is_error") is True:
                    is_error = 1

        full_text = _normalize_text("\n".join(texts)) if texts else None
        if full_text:
            result.events.append(
                NormalizedEvent(
                    event_type=record_type,
                    role=record_type,
                    timestamp=ts,
                    git_branch=git_branch,
                    cwd=cwd,
                    text=full_text,
                    stderr=stderr,
                    is_error=is_error,
                )
            )

        for name, inp in tools:
            result.events.append(
                NormalizedEvent(
                    event_type="tool_use",
                    role="assistant",
                    timestamp=ts,
                    git_branch=git_branch,
                    cwd=cwd,
                    text=f"{name} {inp}",
                    tool_name=name,
                    tool_input=inp,
                )
            )

        if record_type == "assistant":
            usage = msg.get("usage")
            if isinstance(usage, dict):
                result.token_usage = TokenUsageRow(
                    timestamp=ts,
                    model=msg.get("model") if isinstance(msg.get("model"), str) else None,
                    input_tokens=_int_or_none(usage.get("input_tokens")),
                    output_tokens=_int_or_none(usage.get("output_tokens")),
                    cache_read_tokens=_int_or_none(usage.get("cache_read_input_tokens")),
                    cache_create_tokens=_int_or_none(usage.get("cache_creation_input_tokens")),
                )

    return result


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def parse_jsonl_line(line: str, *, warn_unknown: bool = True) -> LineParseResult | None:
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    result = parse_line(raw, warn_unknown=warn_unknown)
    if result.unknown_type:
        logger.warning("Unknown JSONL record type: %s", result.unknown_type)
    return result
