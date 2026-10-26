"""Finds subagent transcripts and writes their measurements to the database (incremental, repeatable)."""
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from . import classify, transcript
from .config import claude_dir
from .scoring import rescore_all


def transcripts() -> list[Path]:
    return sorted((claude_dir() / "projects").glob("*/*/subagents/agent-*.jsonl"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _meta(path: Path) -> dict:
    try:
        return json.loads(path.with_name(path.stem + ".meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ingest(con: sqlite3.Connection, path: Path, rules: dict, force: bool = False, stopped: bool = False) -> bool:
    """Re-measures a changed transcript. Returns True if anything was written."""
    agent_id = path.stem.removeprefix("agent-")
    try:
        st = path.stat()
    except OSError:
        return False
    old = con.execute("SELECT file_size, file_mtime, stop_event FROM tasks WHERE agent_id=?", (agent_id,)).fetchone()
    stopped = stopped or bool(old and old["stop_event"])
    if old and not force and old["file_size"] == st.st_size and old["file_mtime"] == st.st_mtime \
            and bool(old["stop_event"]) == stopped:
        return False

    meta = _meta(path)
    m = transcript.parse(path, rules)
    marks = m.pop("markers")
    finished = bool(meta.get("finished")) or stopped
    stale = time.time() - st.st_mtime > rules["stale_minutes"] * 60
    state = "done" if finished else ("abandoned" if stale else "running")
    if not finished and stale and m["stop_reason"] in transcript.REPORT_STOP_REASONS and m["final_report"]:
        finished, state = True, "done"   # older versions without meta.json
    description = meta.get("description") or m["prompt"][:80]
    row = {
        **m,
        "agent_id": agent_id,
        "project": Path(m["cwd"]).name if m["cwd"] else path.parents[2].name,
        "agent_type": meta.get("agentType") or "unknown",
        "description": description,
        "prompt": m["prompt"][:4000],
        "final_report": m["final_report"][:4000],
        "model": m["model"] or meta.get("model"),
        "category": classify.category(description, m["prompt"], marks["category"], rules),
        "difficulty": classify.difficulty(m["prompt"], len(marks["files"]) + len(marks["commands"]),
                                          marks["difficulty"], rules),
        "task_key": marks["task_key"],
        "cost_usd": classify.cost(m["model"], m, rules),
        "finished": int(finished), "stop_event": int(stopped), "state": state,
        "file": str(path), "file_size": st.st_size, "file_mtime": st.st_mtime, "updated_at": _now(),
    }
    del row["tokens_measured"]
    cols = ", ".join(row)
    marks_sql = ", ".join("?" for _ in row)
    update = ", ".join(f"{c}=excluded.{c}" for c in row if c != "agent_id")
    con.execute(f"INSERT INTO tasks ({cols}) VALUES ({marks_sql}) ON CONFLICT(agent_id) DO UPDATE SET {update}",
                list(row.values()))
    return True


def record_start(con: sqlite3.Connection, agent_id: str, agent_type: str | None, session_id: str | None) -> None:
    """SubagentStart: the transcript may not exist yet; add a placeholder for the live view."""
    con.execute("INSERT OR IGNORE INTO tasks (agent_id, agent_type, session_id, state, started_at, description, "
                "updated_at) VALUES (?, ?, ?, 'running', ?, 'starting…', ?)",
                (agent_id, agent_type or "unknown", session_id, _now(), _now()))
    con.commit()


def scan(con: sqlite3.Connection, rules: dict, running_only: bool = False) -> int:
    if running_only:
        paths = [Path(r["file"]) for r in con.execute(
            "SELECT file FROM tasks WHERE state='running' AND file IS NOT NULL")]
    else:
        paths = transcripts()
    changed = sum(ingest(con, p, rules) for p in paths)
    # Placeholders whose transcript never appeared
    cutoff = datetime.fromtimestamp(time.time() - rules["stale_minutes"] * 60, timezone.utc).isoformat()
    con.execute("UPDATE tasks SET state='abandoned' WHERE state='running' AND file IS NULL AND updated_at < ?",
                (cutoff,))
    if changed:
        rescore_all(con, rules)
    con.commit()
    return changed


def set_vote(con: sqlite3.Connection, agent_id: str, vote: str | None, rules: dict) -> None:
    if vote:
        con.execute("INSERT INTO votes VALUES (?, ?, ?) ON CONFLICT(agent_id) DO UPDATE "
                    "SET vote=excluded.vote, at=excluded.at", (agent_id, vote, _now()))
    else:
        con.execute("DELETE FROM votes WHERE agent_id=?", (agent_id,))
    rescore_all(con, rules)
