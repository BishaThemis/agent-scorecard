"""SQLite store. Raw measurements come from transcripts; scores, tiers and metrics are derived
data that can be recomputed from those measurements at any time.

Tasks are never deleted and events are never changed or deleted; triggers enforce both, so even
a manual SQL statement fails instead of silently rewriting history.
"""
import sqlite3
from pathlib import Path

from .config import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    agent_id TEXT PRIMARY KEY,
    session_id TEXT, project TEXT, cwd TEXT, agent_type TEXT, description TEXT, prompt TEXT, model TEXT,
    category TEXT, difficulty TEXT, task_key TEXT,
    started_at TEXT, ended_at TEXT, duration_s REAL,
    finished INTEGER DEFAULT 0, stop_event INTEGER DEFAULT 0, stop_reason TEXT, final_report TEXT,
    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cache_write_5m INTEGER DEFAULT 0,
    cache_write_1h INTEGER DEFAULT 0, cache_read INTEGER DEFAULT 0, weighted_tokens INTEGER DEFAULT 0,
    cost_usd REAL,
    tool_calls INTEGER DEFAULT 0, tool_errors INTEGER DEFAULT 0, redundant_calls INTEGER DEFAULT 0,
    repeated_errors INTEGER DEFAULT 0, tool_usage TEXT,
    test_runs INTEGER DEFAULT 0, last_test_ok INTEGER, check_runs INTEGER DEFAULT 0,
    last_check_ok INTEGER, regression INTEGER DEFAULT 0, criteria TEXT,
    claims_done INTEGER DEFAULT 0, claims_tests INTEGER DEFAULT 0,
    discloses_unverified INTEGER DEFAULT 0, admits_partial INTEGER DEFAULT 0,
    state TEXT, outcome TEXT, score REAL, measurable_max REAL, tier TEXT,
    breakdown TEXT, flagged INTEGER DEFAULT 0, rules_hash TEXT, reference_ids TEXT,
    file TEXT, file_size INTEGER, file_mtime REAL, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_agent ON tasks (agent_type, started_at);
CREATE INDEX IF NOT EXISTS ix_tasks_state ON tasks (state);
CREATE TABLE IF NOT EXISTS votes (
    agent_id TEXT PRIMARY KEY,
    vote TEXT NOT NULL CHECK (vote IN ('success', 'partial', 'failed')),
    at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL, kind TEXT NOT NULL, agent_id TEXT, data TEXT NOT NULL,
    prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_agent ON events (agent_id);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS tasks_no_delete BEFORE DELETE ON tasks
    BEGIN SELECT RAISE(ABORT, 'tasks cannot be deleted'); END;
"""

# Columns added after v0.1.0; older databases get them on first connect
ADDED_COLUMNS = {"rules_hash": "TEXT", "reference_ids": "TEXT"}


def connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or data_dir() / "scorecard.db", timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    existing = {r["name"] for r in con.execute("PRAGMA table_info(tasks)")}
    for name, kind in ADDED_COLUMNS.items():
        if name not in existing:
            con.execute(f"ALTER TABLE tasks ADD COLUMN {name} {kind}")
    con.commit()
    return con
