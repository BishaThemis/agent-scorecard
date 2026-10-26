"""Agent scorecards, system success metrics and routing suggestions (read-only)."""
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

TIERS = ("diamond", "gold", "silver", "bronze")
FINAL = ("success", "partial", "failed")


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def agent_cards(con: sqlite3.Connection) -> list[dict]:
    groups = defaultdict(list)
    for r in con.execute("SELECT * FROM tasks WHERE outcome IS NOT NULL ORDER BY started_at"):
        groups[r["agent_type"]].append(r)
    cards = []
    for agent, rows in groups.items():
        final = [r for r in rows if r["outcome"] in FINAL]
        ok = [r for r in final if r["outcome"] == "success"]
        cards.append({
            "agent": agent,
            "tasks": len(rows),
            "pending": sum(r["outcome"] == "pending" for r in rows),
            "running": sum(r["outcome"] == "running" for r in rows),
            "success_rate": len(ok) / len(final) if final else None,
            "total_score": sum(r["score"] or 0 for r in final),
            "mean_score": _mean([r["score"] for r in final]),
            "mean_tokens_success": _mean([r["weighted_tokens"] for r in ok]),
            "cost": sum(r["cost_usd"] or 0 for r in rows),
            "tiers": {t: sum(r["tier"] == t for r in rows) for t in TIERS},
            "flagged": sum(r["flagged"] for r in rows),
        })
    return sorted(cards, key=lambda c: -c["total_score"])


def _first_attempt_rate(rows) -> float | None:
    """The same TASK-ID, or the same session + agent + description, counts as a retry.
    Was the first attempt successful?"""
    groups = defaultdict(list)
    for r in rows:
        key = r["task_key"] or (r["session_id"], r["agent_type"], (r["description"] or "").strip().lower())
        groups[key].append(r)
    firsts = [sorted(g, key=lambda r: r["started_at"] or "")[0] for g in groups.values()]
    firsts = [r for r in firsts if r["outcome"] in FINAL]
    return sum(r["outcome"] == "success" for r in firsts) / len(firsts) if firsts else None


def success_metrics(con: sqlite3.Connection, days: int | None = None, offset: int = 0) -> dict:
    """days=7, offset=0 → last 7 days; days=7, offset=7 → the 7 days before that."""
    query, args = "SELECT * FROM tasks WHERE outcome IS NOT NULL AND outcome != 'running'", []
    if days:
        now = datetime.now(timezone.utc)
        query += " AND started_at >= ? AND started_at < ?"
        args = [(now - timedelta(days=days + offset)).isoformat(), (now - timedelta(days=offset)).isoformat()]
    rows = list(con.execute(query, args))
    ok = [r for r in rows if r["outcome"] == "success"]
    priced = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    return {
        "tasks": len(rows),
        "successes": len(ok),
        "tokens_per_success": _mean([r["weighted_tokens"] for r in ok]),
        "cost_per_task": _mean(priced),
        "unpriced": len(rows) - len(priced),
        "first_attempt": _first_attempt_rate(rows),
        "duration_success": _mean([r["duration_s"] for r in ok]),
        "errors": sum(r["tool_errors"] for r in rows),
        "repeated_errors": sum(r["repeated_errors"] for r in rows),
        "redundant": sum(r["redundant_calls"] for r in rows),
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
