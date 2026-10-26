"""Deterministic scoring: 100 points in six sections. No LLM calls.

Each section produces (points, max, measured, note) lines. Points that cannot be measured are not
awarded and are subtracted from the "measurable maximum", so missing data is shown neither as
failure nor as success. The same event is never penalized in two sections.

Notes are stored as translation keys with parameters, so a breakdown can be shown in any language.
"""
import json
import sqlite3

from .config import rules_hash
from .history import append, write_head
from .transcript import REPORT_STOP_REASONS

FINAL_OUTCOMES = ("success", "partial", "failed")


def note(key: str, **params) -> dict:
    return {"key": key, "params": params}


def _line(section, points, maximum, measured, n):
    return {"section": section, "points": round(points, 2), "max": maximum, "measured": measured, "note": n}


def decide_outcome(t: dict, vote: str | None) -> tuple[str, dict]:
    """The task outcome and the reason for it."""
    if t["state"] == "running":
        return "running", note("reason.running")
    if not t["finished"]:
        return "failed", note("reason.unfinished")
    if t["stop_reason"] not in REPORT_STOP_REASONS or not t["final_report"]:
        return "failed", note("reason.no_report", stop=t["stop_reason"] or "-")
    if vote:
        return vote, note("reason.user_vote")
    criteria = json.loads(t["criteria"] or "[]")
    evidence = t["test_runs"] or t["check_runs"] or criteria
    problems = []
    if t["last_test_ok"] == 0:
        problems.append(note("fail.tests"))
    if t["last_check_ok"] == 0:
        problems.append(note("fail.checks"))
    problems += [note("fail.criterion", value=c["value"]) for c in criteria if not c["met"]]
    if problems:
        if t["admits_partial"]:
            return "partial", note("reason.partial_admitted", items=problems)
        return "failed", note("reason.failed", items=problems)
    if evidence:
        if t["admits_partial"]:
            return "partial", note("reason.partial_verified")
        return "success", note("reason.verified")
    return "pending", note("reason.pending")


def _token_points(ratio: float, steps: list) -> float:
    if ratio <= steps[0][0]:
        return steps[0][1]
    for (r1, p1), (r2, p2) in zip(steps, steps[1:]):
        if ratio <= r2:
            return p1 + (p2 - p1) * (ratio - r1) / (r2 - r1)
    return steps[-1][1]


def score(t: dict, vote: str | None, reference: list[int], rules: dict) -> dict:
    S = rules["sections"]
    outcome, reason = decide_outcome(t, vote)
    if outcome == "running":
        return {"outcome": outcome, "score": None, "measurable_max": None, "tier": None, "flagged": 0,
                "breakdown": json.dumps({"reason": reason, "lines": []}, ensure_ascii=False)}
    criteria = json.loads(t["criteria"] or "[]")
    has_evidence = bool(t["test_runs"] or t["check_runs"] or criteria or vote)
    lines = []

    # 1. Task success
    false_claim = outcome in ("failed", "partial") and t["claims_done"] and not t["admits_partial"] \
        and t["finished"] and t["final_report"]
    if outcome == "success":
        lines.append(_line("success", S["success"], S["success"], True, reason))
    elif outcome == "partial":
        lines.append(_line("success", rules["success"]["partial_cap"], S["success"], True, reason))
    else:
        lines.append(_line("success", 0, S["success"], outcome != "pending", reason))
    if false_claim:
        lines.append(_line("false_claim", rules["success"]["false_claim_penalty"], 0, True, note("note.false_claim")))

    # 2. Output quality
    Q = rules["quality"]
    if t["last_test_ok"] is None:
        lines.append(_line("tests", 0, Q["tests"], False, note("note.no_tests")))
    else:
        lines.append(_line("tests", Q["tests"] if t["last_test_ok"] else 0, Q["tests"], True,
                           note("note.tests_passed" if t["last_test_ok"] else "note.tests_failed", n=t["test_runs"])))
    if criteria:
        met = sum(1 for c in criteria if c["met"])
        lines.append(_line("requirements", Q["requirements"] * met / len(criteria), Q["requirements"], True,
                           note("note.criteria", met=met, total=len(criteria))))
    elif vote in ("success", "partial"):
        lines.append(_line("requirements", Q["requirements"] * (1 if vote == "success" else 0.5), Q["requirements"],
                           True, note("note.user_verified")))
    else:
        lines.append(_line("requirements", 0, Q["requirements"], False, note("note.no_criteria")))
    if not (t["test_runs"] or t["check_runs"]):
        lines.append(_line("no_regression", 0, Q["no_regression"], False, note("note.no_checks")))
    else:
        clean = not t["regression"] and t["last_test_ok"] != 0 and t["last_check_ok"] != 0
        lines.append(_line("no_regression", Q["no_regression"] if clean else 0, Q["no_regression"], True,
                           note("note.checks_clean" if clean else "note.checks_dirty")))

    # 3. Token efficiency (requires verified success)
    if outcome != "success":
        lines.append(_line("tokens", 0, S["tokens"], outcome != "pending", note("note.gate_tokens")))
    elif not t["weighted_tokens"]:
        lines.append(_line("tokens", 0, S["tokens"], False, note("note.tokens_unmeasured")))
    elif len(reference) < rules["tokens"]["min_reference_tasks"]:
        lines.append(_line("tokens", 0, S["tokens"], False,
                           note("note.no_reference", n=len(reference), min=rules["tokens"]["min_reference_tasks"])))
    else:
        if rules["tokens"]["reference"] == "median":
            s = sorted(reference)
            ref = s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2
        else:
            ref = sum(reference) / len(reference)
        ratio = t["weighted_tokens"] / ref
        lines.append(_line("tokens", _token_points(ratio, rules["tokens"]["steps"]), S["tokens"], True,
                           note("note.tokens_ratio", tokens=t["weighted_tokens"], ref=round(ref),
                                n=len(reference), ratio=round(ratio, 2))))

    # 4. Tool and command efficiency (requires verified success)
    if outcome != "success":
        lines.append(_line("tools", 0, S["tools"], outcome != "pending", note("note.gate_tools")))
    else:
        pts = max(0, S["tools"] - rules["tools"]["redundant_call_penalty"] * t["redundant_calls"])
        lines.append(_line("tools", pts, S["tools"], True,
                           note("note.tools", calls=t["tool_calls"], waste=t["redundant_calls"])))

    # 5. Error handling; a failed task is not penalized here a second time
    if not t["finished"]:
        lines.append(_line("errors", 0, S["errors"], True, note("note.unfinished_errors")))
    else:
        pts = max(0, S["errors"] - rules["errors"]["repeated_error_penalty"] * t["repeated_errors"])
        lines.append(_line("errors", pts, S["errors"], True,
                           note("note.errors", errors=t["tool_errors"], repeats=t["repeated_errors"])))

    # 6. Reliability
    R = rules["reliability"]
    if false_claim:
        lines.append(_line("reliability", 0, S["reliability"], True, note("note.reliability_dedup")))
    elif not has_evidence and (t["claims_tests"] or t["claims_done"]) and not t["discloses_unverified"]:
        lines.append(_line("reliability", R["unsupported_claim_penalty"], S["reliability"], True,
                           note("note.unsupported_claim")))
    elif has_evidence:
        lines.append(_line("reliability", R["evidence"], S["reliability"], True, note("note.evidence")))
    elif t["discloses_unverified"]:
        lines.append(_line("reliability", R["disclosed"], S["reliability"], True, note("note.disclosed")))
    else:
        lines.append(_line("reliability", 0, S["reliability"], True, note("note.nothing")))

    total = max(0.0, min(100.0, sum(l["points"] for l in lines)))
    measurable = 100 - sum(l["max"] for l in lines if not l["measured"])
    tier = None
    if outcome in FINAL_OUTCOMES:
        tier = next((name for floor, name in rules["tiers"] if total >= floor), "none")
    return {
        "outcome": outcome, "score": round(total, 1), "measurable_max": measurable, "tier": tier,
        "breakdown": json.dumps({"reason": reason, "lines": lines}, ensure_ascii=False),
        "flagged": int(t["redundant_calls"] >= rules["tools"]["review_threshold"] or t["repeated_errors"] >= 2),
    }


def _credited(con: sqlite3.Connection) -> dict[str, tuple[float, str]]:
    """Points already credited per task in the event log, with the last recorded outcome."""
    credited: dict[str, tuple[float, str]] = {}
    for e in con.execute("SELECT agent_id, data FROM events WHERE kind IN ('scored', 'rescored') ORDER BY seq"):
        d = json.loads(e["data"])
        credited[e["agent_id"]] = (credited.get(e["agent_id"], (0.0, ""))[0] + d["delta"], d["outcome"])
    return credited


def rescore_all(con: sqlite3.Connection, rules: dict, reason: str = "new_data", voted: str | None = None) -> None:
    """Scores every task in time order. The token reference only uses successful tasks of the same
    category and difficulty that ended BEFORE the task started, so past scores do not drift.

    Each final score is credited to the event log once; any later change is logged as a separate
    delta with its reason, so corrections stay visible and accumulated points always add up."""
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")   # one writer at a time keeps the hash chain linear
    rh = rules_hash(rules)
    votes = {r["agent_id"]: r["vote"] for r in con.execute("SELECT agent_id, vote FROM votes")}
    tasks = [dict(r) for r in con.execute("SELECT * FROM tasks ORDER BY started_at")]
    credited = _credited(con)
    successes: list[tuple[str, str, str, int, str]] = []   # (ended_at, category, difficulty, tokens, agent_id)
    updates = []
    for t in tasks:
        refs = [(tok, aid) for end, cat, diff, tok, aid in successes
                if cat == t["category"] and diff == t["difficulty"] and t["started_at"] and end
                and end <= t["started_at"]]
        s = score(t, votes.get(t["agent_id"]), [tok for tok, _ in refs], rules)
        if s["outcome"] == "success" and t["weighted_tokens"]:
            successes.append((t["ended_at"], t["category"], t["difficulty"], t["weighted_tokens"], t["agent_id"]))
        used = [aid for _, aid in refs] if s["outcome"] == "success" else []
        updates.append((s["outcome"], s["score"], s["measurable_max"], s["tier"], s["breakdown"], s["flagged"],
                        rh, json.dumps(used), t["agent_id"]))

        credit = s["score"] if s["outcome"] in FINAL_OUTCOMES else 0.0
        if t["rules_hash"] and t["rules_hash"] != rh:
            why = "rules_changed"
        elif voted and t["agent_id"] == voted:
            why = "vote"
        elif t["reference_ids"] is not None and json.loads(t["reference_ids"]) != used:
            why = "reference_changed"   # e.g. a vote on an earlier task changed the comparison set
        else:
            why = "new_data" if voted else reason
        entry = {"agent_type": t["agent_type"], "outcome": s["outcome"], "score": s["score"], "tier": s["tier"],
                 "rules_hash": rh, "reason": why}
        if t["agent_id"] not in credited:
            if s["outcome"] in FINAL_OUTCOMES:
                append(con, "scored", t["agent_id"], {**entry, "delta": credit})
        else:
            before, last_outcome = credited[t["agent_id"]]
            if round(credit - before, 1) != 0 or last_outcome != s["outcome"]:
                append(con, "rescored", t["agent_id"], {**entry, "delta": round(credit - before, 2),
                                                        "old_outcome": last_outcome, "old_points": round(before, 2)})
    con.executemany("UPDATE tasks SET outcome=?, score=?, measurable_max=?, tier=?, breakdown=?, flagged=?, "
                    "rules_hash=?, reference_ids=? WHERE agent_id=?", updates)
    con.commit()
    write_head(con)
