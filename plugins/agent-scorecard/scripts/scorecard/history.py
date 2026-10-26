"""Append-only, hash-chained event log.

Every vote, vote change and score change is an event. Each event stores the hash of the previous
one, so editing or removing a row breaks the chain. The newest (seq, hash) is also written to
chain_head.json outside the database: if rows are cut from the end or the database is swapped for
an older copy, the head no longer matches.

This makes tampering visible; it cannot make it impossible. Anyone who controls the files can
delete both, and verify() then reports a fresh, empty history rather than a broken one.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from .config import data_dir

GENESIS = "0" * 64
HEAD_FILE = "chain_head.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(prev: str, seq: int, at: str, kind: str, agent_id: str | None, data: str) -> str:
    payload = json.dumps([prev, seq, at, kind, agent_id, data], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _head_path(con: sqlite3.Connection):
    # One head file per database file, so test databases do not share a head
    db_file = con.execute("PRAGMA database_list").fetchone()["file"] or "memory"
    name = HEAD_FILE if db_file.endswith("scorecard.db") else f"chain_head-{hashlib.sha1(db_file.encode()).hexdigest()[:8]}.json"
    return data_dir() / name


def append(con: sqlite3.Connection, kind: str, agent_id: str | None, data: dict) -> int:
    """Appends one event inside the caller's write transaction. Call write_head() after commit."""
    last = con.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
    prev = last["hash"] if last else GENESIS
    seq = (last["seq"] if last else 0) + 1
    at = _now()
    body = json.dumps(data, sort_keys=True, ensure_ascii=False)
    con.execute("INSERT INTO events (seq, at, kind, agent_id, data, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (seq, at, kind, agent_id, body, prev, _digest(prev, seq, at, kind, agent_id, body)))
    return seq


def write_head(con: sqlite3.Connection) -> None:
    last = con.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
    if last:
        _head_path(con).write_text(json.dumps({"seq": last["seq"], "hash": last["hash"]}), encoding="utf-8")


def verify(con: sqlite3.Connection) -> dict:
    """Checks the whole chain. Returns {"ok", "events", "problem", "seq", "missing_tasks"}."""
    prev, expected_seq, count = GENESIS, 1, 0
    for e in con.execute("SELECT * FROM events ORDER BY seq"):
        count += 1
        if e["seq"] != expected_seq:
            return {"ok": False, "events": count, "problem": "gap", "seq": expected_seq, "missing_tasks": 0}
        if e["prev_hash"] != prev or e["hash"] != _digest(prev, e["seq"], e["at"], e["kind"], e["agent_id"], e["data"]):
            return {"ok": False, "events": count, "problem": "modified", "seq": e["seq"], "missing_tasks": 0}
        prev, expected_seq = e["hash"], expected_seq + 1
    head_path = _head_path(con)
    if head_path.exists():
        head = json.loads(head_path.read_text(encoding="utf-8"))
        row = con.execute("SELECT hash FROM events WHERE seq=?", (head["seq"],)).fetchone()
        if not row or row["hash"] != head["hash"]:
            return {"ok": False, "events": count, "problem": "truncated", "seq": head["seq"], "missing_tasks": 0}
    missing = con.execute("SELECT COUNT(DISTINCT agent_id) FROM events WHERE kind='scored' "
                          "AND agent_id NOT IN (SELECT agent_id FROM tasks)").fetchone()[0]
    return {"ok": missing == 0, "events": count, "problem": "missing_tasks" if missing else None, "seq": None,
            "missing_tasks": missing}


def events(con: sqlite3.Connection, agent_type: str | None = None, limit: int = 2000) -> list[dict]:
    rows = []
    for e in con.execute("SELECT * FROM events ORDER BY seq DESC LIMIT ?", (limit if not agent_type else -1,)):
        d = json.loads(e["data"])
        if agent_type and d.get("agent_type") != agent_type:
            continue
        rows.append({"seq": e["seq"], "at": e["at"], "kind": e["kind"], "agent_id": e["agent_id"], **d})
    return rows[:limit]


def career_points(con: sqlite3.Connection) -> dict[str, float]:
    """Accumulated points per agent type: the sum of score deltas in the log. Kept apart from
    per-task scores, and every correction shows up as its own positive or negative delta."""
    totals: dict[str, float] = {}
    for e in con.execute("SELECT data FROM events WHERE kind IN ('scored', 'rescored')"):
        d = json.loads(e["data"])
        totals[d["agent_type"]] = totals.get(d["agent_type"], 0.0) + d["delta"]
    return totals


def ledger(con: sqlite3.Connection, agent_type: str) -> list[tuple[str, float, float]]:
    """(time, delta, running total) for one agent, oldest first."""
    total, rows = 0.0, []
    for e in con.execute("SELECT at, data FROM events WHERE kind IN ('scored', 'rescored') ORDER BY seq"):
        d = json.loads(e["data"])
        if d["agent_type"] == agent_type:
            total += d["delta"]
            rows.append((e["at"], d["delta"], total))
    return rows
