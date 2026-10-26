"""CSV and JSON export of tasks, task groups and the event log."""
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config, history, metrics

# Long free-text columns are left out of CSV to keep it spreadsheet-friendly; JSON has everything
CSV_SKIP = {"prompt", "final_report", "breakdown", "tool_usage", "criteria", "file"}


def export_csv(con: sqlite3.Connection, path: Path) -> int:
    rows = list(con.execute("SELECT * FROM tasks ORDER BY started_at"))
    columns = [c for c in (rows[0].keys() if rows else []) if c not in CSV_SKIP]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # BOM so Excel reads UTF-8
        writer = csv.writer(f)
        writer.writerow(columns)
        for r in rows:
            writer.writerow([r[c] for c in columns])
    return len(rows)


def export_json(con: sqlite3.Connection, path: Path, rules: dict) -> int:
    tasks = []
    for r in con.execute("SELECT * FROM tasks ORDER BY started_at"):
        t = dict(r)
        for key in ("breakdown", "tool_usage", "criteria", "reference_ids"):
            t[key] = json.loads(t[key]) if t[key] else None
        tasks.append(t)
    groups = [{k: v for k, v in g.items() if k != "key"} for g in metrics.task_groups(con)]
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rules_hash": config.rules_hash(rules),
        "chain": history.verify(con),
        "career_points": history.career_points(con),
        "tasks": tasks,
        "task_groups": groups,
        "events": [dict(e) for e in con.execute("SELECT * FROM events ORDER BY seq")],
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return len(tasks)
