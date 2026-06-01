import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ingest  # noqa: E402
import paths  # noqa: E402
import store  # noqa: E402


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


def test_ingest_and_search(fixture_projects):
    stats = ingest.ingest_all()
    assert stats["lines_ingested"] >= 4

    conn = store.ensure_db()
    row = conn.execute(
        "SELECT title FROM sessions WHERE session_id = ?", ("sess-test-001",)
    ).fetchone()
    assert row["title"] == "Auth middleware fix"

    events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert events >= 3


def test_reindex(fixture_projects):
    ingest.ingest_all()
    ingest.reindex()
    conn = store.ensure_db()
    assert store.db_stats(conn)["sessions"] == 1
