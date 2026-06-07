import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ingest  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402
from cost import format_cost_tips  # noqa: E402
from parser import parse_jsonl_line  # noqa: E402
from queries import tool_usage_totals  # noqa: E402
from tips import analyze_tips, format_tips  # noqa: E402


@pytest.fixture
def fixture_projects(tmp_path, monkeypatch):
    projects = tmp_path / "projects" / "-tmp-demo-project"
    projects.mkdir(parents=True)
    data_dir = tmp_path / "retroscope"
    fixture = ROOT / "tests" / "fixtures" / "sample.jsonl"
    (projects / "sess-test-001.jsonl").write_text(fixture.read_text())

    monkeypatch.setenv("RETROSCOPE_DATA_DIR", str(data_dir))
    monkeypatch.setattr(paths, "projects_dir", lambda: tmp_path / "projects")
    monkeypatch.setattr(ingest, "projects_dir", paths.projects_dir)
    return tmp_path


def test_token_usage_parsed():
    line = json.dumps(
        {
            "type": "assistant",
            "timestamp": "2026-06-01T10:00:00.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 50,
                },
            },
        }
    )
    result = parse_jsonl_line(line)
    assert result.token_usage is not None
    assert result.token_usage.input_tokens == 10
    assert result.token_usage.cache_create_tokens == 50


def test_session_metrics(fixture_projects):
    ingest.ingest_all()
    conn = store.ensure_db()

    token_count = conn.execute("SELECT COUNT(*) FROM token_usage").fetchone()[0]
    assert token_count >= 2

    row = conn.execute(
        "SELECT * FROM session_metrics WHERE session_id = ?", ("sess-test-001",)
    ).fetchone()
    assert row is not None
    assert row["user_turns"] >= 3
    assert row["skill_reads"] >= 2
    assert row["repeated_skill_reads"] >= 1
    assert row["correction_signals"] >= 1


def test_fts_indexed(fixture_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    fts_count = conn.execute("SELECT COUNT(*) FROM events_fts").fetchone()[0]
    assert fts_count >= 3


def test_tips_detects_patterns(fixture_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    tips = analyze_tips(conn, since="7d")
    categories = {t.category for t in tips}
    assert "skills" in categories or "corrections" in categories


def test_cost_tips_output(fixture_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    output = format_cost_tips(conn, since="7d")
    assert "Cost Tips" in output
    assert "token" in output.lower() or "Token" in output


def test_tips_format(fixture_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    output = format_tips(conn, since="7d")
    assert "Workflow Tips" in output


def test_tool_usage_totals_excludes_retroscope(fixture_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    # Insert a fake retroscope tool_use event into the session
    conn.execute(
        """
        INSERT INTO events (session_id, event_type, tool_name, timestamp)
        VALUES ('sess-test-001', 'tool_use', 'mcp__plugin_retroscope_retroscope__retroscope_standup', '2026-06-01T10:00:08.000Z')
        """
    )
    conn.commit()
    rows = tool_usage_totals(conn, since_iso="2026-01-01T00:00:00")
    tool_names = [r["tool_name"] for r in rows]
    assert not any("mcp__plugin_retroscope_" in name for name in tool_names)
