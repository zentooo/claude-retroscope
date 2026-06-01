import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from parser import parse_jsonl_line  # noqa: E402


def test_parse_user_and_assistant():
    line = json.dumps(
        {
            "type": "user",
            "timestamp": "2026-06-01T10:00:00.000Z",
            "cwd": "/tmp/demo",
            "gitBranch": "main",
            "message": {"role": "user", "content": "hello"},
        }
    )
    result = parse_jsonl_line(line)
    assert result is not None
    assert len(result.events) == 1
    assert result.events[0].role == "user"
    assert "hello" in result.events[0].text


def test_parse_ai_title():
    line = json.dumps(
        {"type": "ai-title", "timestamp": "2026-06-01T10:00:00.000Z", "aiTitle": "My title"}
    )
    result = parse_jsonl_line(line)
    assert result.title == "My title"


def test_unknown_type_warns(caplog):
    line = json.dumps({"type": "future-type", "data": 1})
    with caplog.at_level("WARNING"):
        result = parse_jsonl_line(line)
    assert result.unknown_type == "future-type"
