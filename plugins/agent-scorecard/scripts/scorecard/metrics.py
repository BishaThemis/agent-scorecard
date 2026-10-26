"""Agent scorecards, profiles, task groups, period summaries and routing suggestions (read-only)."""
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from . import history

TIERS = ("diamond", "gold", "silver", "bronze")
FINAL = ("success", "partial", "failed")


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _local_date(ts: str | None) -> date | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
    except (AttributeError, ValueError):
        return None


# ---------- levels ----------

def level_of(points: float, rules: dict) -> dict:
    """Levels only describe accumulated history. Nothing in scoring reads them."""
    steps = rules["levels"]
    index = max(i for i, (floor, _) in enumerate(steps) if points >= floor) if points >= steps[0][0] else 0
    floor, key = steps[index]
    nxt = steps[index + 1] if index + 1 < len(steps) else None
    progress = 1.0 if not nxt else max(0.0, min(1.0, (points - floor) / (nxt[0] - floor)))
    return {"key": key, "floor": floor, "next_key": nxt[1] if nxt else None, "next_floor": nxt[0] if nxt else None,
            "progress": progress}


# ---------- task groups ----------

def group_key(r) -> tuple:
    """TASK-ID groups exactly. Without one, the same session + description is treated as the same
    task (retries and hand-offs between agents), which is only an approximation."""
    if r["task_key"]:
        return ("id", r["task_key"])
    return ("approx", r["session_id"], (r["description"] or "").strip().lower())


def _groups(rows) -> list[dict]:
    buckets = defaultdict(list)
    for r in rows:
        buckets[group_key(r)].append(r)
    result = []
    for key, members in buckets.items():
        members.sort(key=lambda r: r["started_at"] or "")
        priced = all(r["cost_usd"] is not None for r in members)
        result.append({
            "key": key, "exact": key[0] == "id", "label": key[1] if key[0] == "id" else members[0]["description"],
            "attempts": len(members), "agents": sorted({r["agent_type"] for r in members}),
            "tokens": sum(r["weighted_tokens"] or 0 for r in members),
            "cost": sum(r["cost_usd"] or 0 for r in members), "priced": priced,
            "outcome": members[-1]["outcome"], "first_outcome": members[0]["outcome"],
            "started": members[0]["started_at"], "ended": max((r["ended_at"] or "") for r in members) or None,
            "project": members[0]["project"], "members": [r["agent_id"] for r in members],
        })
    return sorted(result, key=lambda g: g["started"] or "", reverse=True)


def task_groups(con: sqlite3.Connection) -> list[dict]:
    return _groups(list(con.execute("SELECT * FROM tasks WHERE outcome IS NOT NULL")))


# ---------- summaries ----------

def _summarize(rows) -> dict:
    ok = [r for r in rows if r["outcome"] == "success"]
    final = [r for r in rows if r["outcome"] in FINAL]
    groups = _groups(rows)
    priced = [g["cost"] for g in groups if g["priced"]]
    firsts = [g for g in groups if g["first_outcome"] in FINAL]
    return {
        "tasks": len(rows),
        "successes": len(ok),
        "success_rate": len(ok) / len(final) if final else None,
        "tokens_per_success": _mean([r["weighted_tokens"] for r in ok]),
        "cost_per_task": _mean(priced),
        "unpriced": len(groups) - len(priced),
        "groups": len(groups),
        "first_attempt": sum(g["first_outcome"] == "success" for g in firsts) / len(firsts) if firsts else None,
        "duration_success": _mean([r["duration_s"] for r in ok]),
        "test_pass": _mean([r["last_test_ok"] for r in final if r["last_test_ok"] is not None]),
        "errors": sum(r["tool_errors"] for r in rows),
        "repeated_errors": sum(r["repeated_errors"] for r in rows),
        "redundant": sum(r["redundant_calls"] for r in rows),
    }


def success_metrics(con: sqlite3.Connection, days: int | None = None, offset: int = 0) -> dict:
    """days=7, offset=0 → last 7 days; days=7, offset=7 → the 7 days before that."""
    query, args = "SELECT * FROM tasks WHERE outcome IS NOT NULL AND outcome != 'running'", []
    if days:
        now = datetime.now(timezone.utc)
        query += " AND started_at >= ? AND started_at < ?"
        args = [(now - timedelta(days=days + offset)).isoformat(), (now - timedelta(days=offset)).isoformat()]
    return _summarize(list(con.execute(query, args)))


def period_summary(con: sqlite3.Connection, unit: str = "day", count: int = 14) -> list[dict]:
    """One row per local day or per week (starting Monday), newest first, empty periods included."""
    today = datetime.now().astimezone().date()

    def start_of(d: date) -> date:
        return d - timedelta(days=d.weekday()) if unit == "week" else d

    step = timedelta(days=7 if unit == "week" else 1)
    starts = [start_of(today) - i * step for i in range(count)]
    buckets = defaultdict(list)
    for r in con.execute("SELECT * FROM tasks WHERE outcome IS NOT NULL AND outcome != 'running'"):
        d = _local_date(r["started_at"])
        if d:
            buckets[start_of(d)].append(r)
    return [{"start": s, **_summarize(buckets.get(s, []))} for s in starts]


# ---------- per agent ----------

def agent_cards(con: sqlite3.Connection, rules: dict | None = None) -> list[dict]:
    groups = defaultdict(list)
    for r in con.execute("SELECT * FROM tasks WHERE outcome IS NOT NULL ORDER BY started_at"):
        groups[r["agent_type"]].append(r)
    career = history.career_points(con)
    cards = []
    for agent, rows in groups.items():
        final = [r for r in rows if r["outcome"] in FINAL]
        ok = [r for r in final if r["outcome"] == "success"]
        cards.append({
            "agent": agent,
            "tasks": len(rows),
            "pending": sum(r["outcome"] == "pending" for r in rows),
            "running": sum(r["outcome"] == "running" for r in rows),
            "final": len(final),
            "success_rate": len(ok) / len(final) if final else None,
            "career": career.get(agent, 0.0),
            "level": level_of(career.get(agent, 0.0), rules)["key"] if rules else None,
            "mean_score": _mean([r["score"] for r in final]),
            "mean_tokens_success": _mean([r["weighted_tokens"] for r in ok]),
            "cost": sum(r["cost_usd"] or 0 for r in rows),
            "tiers": {t: sum(r["tier"] == t for r in rows) for t in TIERS},
            "flagged": sum(r["flagged"] for r in rows),
        })
    return sorted(cards, key=lambda c: -c["career"])


def agent_profile(con: sqlite3.Connection, agent: str, rules: dict) -> dict:
    rows = list(con.execute("SELECT * FROM tasks WHERE agent_type=? AND outcome IS NOT NULL ORDER BY started_at",
                            (agent,)))
    final = [r for r in rows if r["outcome"] in FINAL]
    ok = [r for r in final if r["outcome"] == "success"]
    min_tasks = rules["routing"]["min_tasks"]

    gained = lost = 0.0
    for r in final:
        for line in json.loads(r["breakdown"] or "{}").get("lines", []):
            if line["points"] > 0:
                gained += line["points"]
            else:
                lost -= line["points"]

    tools, tool_errors = Counter(), Counter()
    for r in rows:
        for name, (calls, errors) in json.loads(r["tool_usage"] or "{}").items():
            tools[name] += calls
            tool_errors[name] += errors

    by_category = defaultdict(list)
    for r in final:
        by_category[(r["category"], r["difficulty"])].append(r)
    categories = sorted(({
        "category": cat, "difficulty": diff, "n": len(rs), "reliable": len(rs) >= min_tasks,
        "success_rate": sum(r["outcome"] == "success" for r in rs) / len(rs),
        "mean_score": _mean([r["score"] for r in rs]),
    } for (cat, diff), rs in by_category.items()), key=lambda c: (not c["reliable"], -(c["mean_score"] or 0)))

    today = datetime.now().astimezone().date()
    monday = today - timedelta(days=today.weekday())
    weeks = []
    for i in range(7, -1, -1):
        start = monday - timedelta(weeks=i)
        rs = [r for r in final if (d := _local_date(r["started_at"])) and start <= d < start + timedelta(weeks=1)]
        weeks.append({"start": start, "n": len(rs), "mean_score": _mean([r["score"] for r in rs]),
                      "success_rate": sum(r["outcome"] == "success" for r in rs) / len(rs) if rs else None})

    points = history.career_points(con).get(agent, 0.0)
    level_ups, current = [], level_of(0, rules)["key"]
    for at, _delta, total in history.ledger(con, agent):
        key = level_of(total, rules)["key"]
        if key != current:
            level_ups.append({"at": at, "level": key, "up": [k for _, k in rules["levels"]].index(key)
                              > [k for _, k in rules["levels"]].index(current)})
            current = key

    return {
        "agent": agent, "tasks": len(rows), "final": len(final), "reliable": len(final) >= min_tasks,
        "counts": Counter(r["outcome"] for r in rows),
        "success_rate": len(ok) / len(final) if final else None,
        "career": points, "level": level_of(points, rules), "level_ups": level_ups,
        "gained": gained, "lost": lost,
        "tokens": sum(r["weighted_tokens"] or 0 for r in rows),
        "input": sum(r["input_tokens"] or 0 for r in rows), "output": sum(r["output_tokens"] or 0 for r in rows),
        "cache_write": sum((r["cache_write_5m"] or 0) + (r["cache_write_1h"] or 0) for r in rows),
        "cache_read": sum(r["cache_read"] or 0 for r in rows),
        "tokens_per_success": _mean([r["weighted_tokens"] for r in ok]),
        "cost": sum(r["cost_usd"] or 0 for r in rows), "unpriced": sum(r["cost_usd"] is None for r in rows),
        "duration_success": _mean([r["duration_s"] for r in ok]),
        "tools": [(name, n, tool_errors[name]) for name, n in tools.most_common()],
        "tool_errors": sum(r["tool_errors"] for r in rows), "repeated_errors": sum(r["repeated_errors"] for r in rows),
        "redundant": sum(r["redundant_calls"] for r in rows),
        "failures": [r for r in reversed(rows) if r["outcome"] in ("failed", "partial")],
        "categories": categories, "weeks": weeks,
    }


def routing(con: sqlite3.Connection, min_tasks: int) -> list[dict]:
    """Ranks agents by mean score within each category + difficulty. No suggestion on thin data."""
    groups = defaultdict(lambda: defaultdict(list))
    for r in con.execute(f"SELECT * FROM tasks WHERE outcome IN {FINAL}"):
        groups[(r["category"], r["difficulty"])][r["agent_type"]].append(r)
    result = []
    for (cat, diff), agents in sorted(groups.items()):
        ranking = [{
            "agent": agent, "n": len(rows), "mean_score": _mean([r["score"] for r in rows]),
            "success": sum(r["outcome"] == "success" for r in rows) / len(rows),
            "mean_tokens": _mean([r["weighted_tokens"] for r in rows if r["outcome"] == "success"]),
        } for agent, rows in agents.items()]
        enough = sorted([x for x in ranking if x["n"] >= min_tasks], key=lambda x: -(x["mean_score"] or 0))
        result.append({"category": cat, "difficulty": diff, "best": enough[0] if enough else None,
                       "runner_up": enough[1] if len(enough) > 1 else None,
                       "total": sum(x["n"] for x in ranking), "agents": len(ranking)})
    return result
