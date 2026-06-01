-- Retroscope index schema (Phase 1)

CREATE TABLE IF NOT EXISTS ingest_state (
  file_path     TEXT PRIMARY KEY,
  file_mtime    REAL NOT NULL,
  byte_offset   INTEGER NOT NULL DEFAULT 0,
  line_count    INTEGER NOT NULL DEFAULT 0,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id    TEXT PRIMARY KEY,
  project_key   TEXT NOT NULL,
  cwd           TEXT,
  slug          TEXT,
  title         TEXT,
  git_branch    TEXT,
  started_at    TEXT,
  ended_at      TEXT,
  message_count INTEGER DEFAULT 0,
  is_subagent   INTEGER DEFAULT 0,
  source        TEXT DEFAULT 'cli',
  link_status   TEXT DEFAULT 'linked'
);

CREATE TABLE IF NOT EXISTS events (
  id            INTEGER PRIMARY KEY,
  session_id    TEXT NOT NULL,
  event_type    TEXT NOT NULL,
  timestamp     TEXT,
  role          TEXT,
  git_branch    TEXT,
  cwd           TEXT,
  text          TEXT,
  tool_name     TEXT,
  tool_input    TEXT,
  stderr        TEXT,
  is_error      INTEGER DEFAULT 0,
  FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);

CREATE TABLE IF NOT EXISTS token_usage (
  id                  INTEGER PRIMARY KEY,
  session_id          TEXT NOT NULL,
  timestamp           TEXT,
  model               TEXT,
  input_tokens        INTEGER,
  output_tokens       INTEGER,
  cache_read_tokens   INTEGER,
  cache_create_tokens INTEGER,
  FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS session_metrics (
  session_id              TEXT PRIMARY KEY,
  user_turns              INTEGER,
  tool_calls              INTEGER,
  skill_reads             INTEGER,
  repeated_skill_reads    INTEGER,
  pasted_chars            INTEGER,
  correction_signals      INTEGER,
  FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS plans (
  slug          TEXT PRIMARY KEY,
  title         TEXT,
  plan_path     TEXT,
  updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS plan_sessions (
  slug          TEXT,
  session_id    TEXT,
  PRIMARY KEY (slug, session_id)
);
