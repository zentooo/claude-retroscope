import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ingest  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402
from improve import _looks_like_paste, analyze_friction, format_improve  # noqa: E402


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _session_lines(cwd: str, *, error_stderr: str, correction: str) -> list[dict]:
    return [
        {
            "type": "user",
            "timestamp": _ts(24),
            "cwd": cwd,
            "gitBranch": "main",
            "message": {"role": "user", "content": "do the thing"},
        },
        {
            "type": "user",
            "timestamp": _ts(23),
            "cwd": cwd,
            "gitBranch": "main",
            "message": {"role": "user", "content": "tool output"},
            "toolUseResult": {"is_error": True, "stderr": error_stderr},
        },
        {
            "type": "user",
            "timestamp": _ts(22),
            "cwd": cwd,
            "gitBranch": "main",
            "message": {"role": "user", "content": correction},
        },
    ]


@pytest.fixture
def friction_projects(tmp_path, monkeypatch):
    cwd = "/tmp/friction-proj"
    proj_dir = tmp_path / "projects" / "-tmp-friction-proj"
    proj_dir.mkdir(parents=True)

    err = "npm ERR! Build failed: cannot find module 'foo' at /repo/src/index.ts:42"
    for sid, correction in (
        ("sess-a", "No, that is wrong. use vitest instead of jest please"),
        ("sess-b", "違う、もう一度。use vitest instead of jest"),
    ):
        lines = _session_lines(cwd, error_stderr=err, correction=correction)
        (proj_dir / f"{sid}.jsonl").write_text(
            "\n".join(json.dumps(line) for line in lines)
        )

    monkeypatch.setenv("RETROSCOPE_DATA_DIR", str(tmp_path / "retroscope"))
    monkeypatch.setattr(paths, "projects_dir", lambda: tmp_path / "projects")
    monkeypatch.setattr(ingest, "projects_dir", paths.projects_dir)
    return tmp_path


def test_detects_recurring_error_and_correction(friction_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    signals = analyze_friction(conn, since="7d")
    kinds = {s.kind for s in signals}
    assert "recurring_error" in kinds
    assert "tool_preference" in kinds
    assert "repeated_correction" in kinds

    pref = next(s for s in signals if s.kind == "tool_preference")
    assert "vitest" in pref.summary and "jest" in pref.summary
    assert pref.count >= 2


def test_focus_filters_categories(friction_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    errors_only = analyze_friction(conn, since="7d", focus="errors")
    assert errors_only and all(s.kind == "recurring_error" for s in errors_only)


def test_unknown_focus_raises(friction_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    with pytest.raises(ValueError):
        analyze_friction(conn, since="7d", focus="bogus")


def test_format_improve_output(friction_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    output = format_improve(conn, since="7d")
    assert "Improvement Suggestions" in output
    assert "CLAUDE.md" in output
    assert "vitest" in output


def test_looks_like_paste_filters_noise():
    diff = "diff --git a/x.md b/x.md index 96f6e08..1b91f66 100644 use a not b"
    code = '"""module""" from __future__ import annotations use a not b'
    assert _looks_like_paste(diff)
    assert _looks_like_paste(code)
    assert not _looks_like_paste("No, use vitest instead of jest please")


def test_pasted_diff_not_counted_as_correction(tmp_path, monkeypatch):
    cwd = "/tmp/paste-proj"
    proj_dir = tmp_path / "projects" / "-tmp-paste-proj"
    proj_dir.mkdir(parents=True)
    # A pasted diff that happens to contain "not" — must not become a signal.
    lines = [
        {
            "type": "user",
            "timestamp": _ts(20),
            "cwd": cwd,
            "gitBranch": "main",
            "message": {
                "role": "user",
                "content": "diff --git a/a.py b/a.py use jest not vitest here",
            },
        },
        {
            "type": "user",
            "timestamp": _ts(19),
            "cwd": cwd,
            "gitBranch": "main",
            "message": {
                "role": "user",
                "content": "diff --git a/b.py b/b.py use jest not vitest here",
            },
        },
    ]
    (proj_dir / "sess-p.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    monkeypatch.setenv("RETROSCOPE_DATA_DIR", str(tmp_path / "retroscope"))
    monkeypatch.setattr(paths, "projects_dir", lambda: tmp_path / "projects")
    monkeypatch.setattr(ingest, "projects_dir", paths.projects_dir)

    ingest.ingest_all()
    conn = store.ensure_db()
    assert analyze_friction(conn, since="7d", focus="corrections") == []


def test_stable_days_excludes_recent(friction_projects):
    ingest.ingest_all()
    conn = store.ensure_db()
    # All fixture activity is within the last day; excluding 2 days drops it all.
    signals = analyze_friction(conn, since="30d", stable_days=2)
    assert signals == []
