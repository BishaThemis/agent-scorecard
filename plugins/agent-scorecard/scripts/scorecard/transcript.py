"""Extracts verifiable measurements from a subagent transcript (subagents/agent-*.jsonl).

Nothing is interpreted here; only what is actually in the record is counted.
Scoring decisions live in scoring.py.
"""
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

HANDBACK_TOOL = "SubagentHandback"
REPORT_STOP_REASONS = ("end_turn", "stop_sequence", "handback")

MARKER = re.compile(
    r"^\s*(ACCEPT-FILE|KABUL-DOSYA|ACCEPT-CMD|KABUL-KOMUT|DIFFICULTY|ZORLUK|CATEGORY|KATEGOR[İI]|TASK-ID|GOREV-ID|GÖREV-ID)"
    r"\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
DIFFICULTY_ALIASES = {"easy": "easy", "kolay": "easy", "medium": "medium", "orta": "medium",
                      "hard": "hard", "zor": "hard"}


def _time(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _digest(content) -> str:
    """Fingerprint of a tool result, to tell whether two calls produced the same output."""
    if isinstance(content, list):
        content = json.dumps([c.get("text", c) if isinstance(c, dict) else c for c in content],
                             ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(str(content).encode("utf-8", "replace")).hexdigest()


def lower(text: str) -> str:
    """Lowercase that handles Turkish dotted and dotless I."""
    return text.replace("İ", "i").replace("I", "ı").lower() if re.search("[çğıöşüÇĞİÖŞÜ]", text) else text.lower()


def matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def markers(prompt: str) -> dict:
    """Machine-readable lines the orchestrating agent can put in a task prompt:
    ACCEPT-FILE: path   ACCEPT-CMD: text   DIFFICULTY: easy|medium|hard   CATEGORY: name   TASK-ID: key
    (Turkish aliases KABUL-DOSYA, KABUL-KOMUT, ZORLUK, KATEGORI, GOREV-ID are also accepted.)"""
    result = {"files": [], "commands": [], "difficulty": None, "category": None, "task_key": None}
    for key, value in MARKER.findall(prompt or ""):
        k = key.upper().replace("İ", "I").replace("Ö", "O")
        value = value.strip("`'\"")
        if k in ("ACCEPT-FILE", "KABUL-DOSYA"):
            result["files"].append(value)
        elif k in ("ACCEPT-CMD", "KABUL-KOMUT"):
            result["commands"].append(value)
        elif k in ("DIFFICULTY", "ZORLUK"):
            result["difficulty"] = DIFFICULTY_ALIASES.get(lower(value))
        elif k in ("CATEGORY", "KATEGORI"):
            result["category"] = lower(value)
        else:
            result["task_key"] = value
    return result


def parse(path: Path, rules: dict) -> dict:
    usage: dict[str, dict] = {}
    calls: list[dict] = []
    results: dict[str, tuple[bool, str]] = {}
    prompt = cwd = session = model = None
    first_ts = last_ts = None
    last_msg_id, last_text, stop_reason = None, [], None
    handback = None

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # last line may still be being written
            kind = entry.get("type")
            if kind not in ("user", "assistant"):
                continue
            ts = entry.get("timestamp")
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            cwd = cwd or entry.get("cwd")
            session = session or entry.get("sessionId")
            message = entry.get("message") or {}
            content = message.get("content")

            if kind == "user":
                if isinstance(content, str):
                    prompt = prompt if prompt is not None else content
                elif isinstance(content, list):
                    for block in content:
                        if block.get("type") == "tool_result":
                            results[block.get("tool_use_id")] = (bool(block.get("is_error")),
                                                                 _digest(block.get("content")))
                        elif block.get("type") == "text" and prompt is None:
                            prompt = block.get("text", "")
                continue

            # assistant: one API message is split over several lines, each repeating the same usage
            msg_id = message.get("id")
            if msg_id and message.get("usage"):
                usage[msg_id] = message["usage"]
            model = message.get("model") or model
            if msg_id != last_msg_id:
                last_msg_id, last_text = msg_id, []
            if message.get("stop_reason"):
                stop_reason = message["stop_reason"]
            for block in content or []:
                if block.get("type") == "text":
                    last_text.append(block.get("text", ""))
                elif block.get("type") == "tool_use" and block.get("name") == HANDBACK_TOOL:
                    # Newer versions deliver the final report through this tool; it is not work
                    handback = (block.get("id"), str((block.get("input") or {}).get("message", "")))
                elif block.get("type") == "tool_use":
                    args = block.get("input") or {}
                    calls.append({
                        "id": block.get("id"),
                        "name": block.get("name"),
                        "key": block.get("name", "") + json.dumps(args, sort_keys=True, ensure_ascii=False),
                        "command": args.get("command") if isinstance(args.get("command"), str) else None,
                        "file": args.get("file_path") or args.get("notebook_path"),
                    })

    # --- tokens ---
    inp = out = w5 = w1 = read = 0
    for u in usage.values():
        inp += u.get("input_tokens") or 0
        out += u.get("output_tokens") or 0
        read += u.get("cache_read_input_tokens") or 0
        detail = u.get("cache_creation") or {}
        if detail:
            w5 += detail.get("ephemeral_5m_input_tokens") or 0
            w1 += detail.get("ephemeral_1h_input_tokens") or 0
        else:
            w5 += u.get("cache_creation_input_tokens") or 0
    weighted = round(inp + out + w5 + w1 + read * rules["tokens"]["cache_read_weight"])

    # --- tool calls ---
    state_changing = set(rules["state_changing_tools"])
    command_tools = set(rules["command_tools"])
    test_p, check_p = rules["patterns"]["test"], rules["patterns"]["check"]
    last_seen: dict[str, int] = {}
    last_change = -1
    redundant = repeated_errors = errors = 0
    usage_by_tool: Counter = Counter()
    errors_by_tool: Counter = Counter()
    tests, checks = [], []
    for i, call in enumerate(calls):
        failed, digest = results.get(call["id"], (None, None))
        call["error"], call["digest"] = failed, digest
        usage_by_tool[call["name"]] += 1
        if failed:
            errors += 1
            errors_by_tool[call["name"]] += 1
        call["verify"] = None
        if call["name"] in command_tools and call["command"]:
            if matches(call["command"], test_p):
                call["verify"] = "test"
            elif matches(call["command"], check_p):
                call["verify"] = "check"
        if failed is not None and call["verify"]:
            (tests if call["verify"] == "test" else checks).append(not failed)

        previous = last_seen.get(call["key"])
        # Nothing state-changing has run since the previous identical call
        if previous is not None and last_change <= previous and failed is not None:
            prev = calls[previous]
            if prev["error"]:
                repeated_errors += 1    # retrying the same failure without changing anything
            elif not failed and prev["digest"] == digest and not call["verify"]:
                redundant += 1          # same input, same output: no progress
        last_seen[call["key"]] = i
        if call["name"] in state_changing:
            last_change = i

    def last(values):
        return None if not values else int(values[-1])

    # Regression: a kind of check that passed earlier fails at the end
    regression = int(any(v and any(v) and not v[-1] for v in (tests, checks)))

    # --- markers and acceptance criteria ---
    marks = markers(prompt or "")
    written = {os.path.normcase(os.path.abspath(os.path.join(cwd or "", c["file"])))
               for c in calls if c["name"] in rules["file_writing_tools"] and c["file"] and c["error"] is False}
    all_commands = "\n".join(c["command"] or "" for c in calls)
    criteria = []
    for rel in marks["files"]:
        full = os.path.normcase(os.path.abspath(os.path.join(cwd or "", rel)))
        exists = os.path.exists(full)
        own = full in written or rel in all_commands
        criteria.append({"kind": "file", "value": rel, "met": exists and own,
                         "note": "" if exists and own else ("missing" if not exists else "not_written_by_agent")})
    for text in marks["commands"]:
        related = [c for c in calls if c["command"] and text in c["command"] and c["error"] is not None]
        criteria.append({"kind": "command", "value": text, "met": bool(related) and not related[-1]["error"],
                         "note": "" if related else "not_run"})

    report = "\n".join(last_text).strip()
    if handback and results.get(handback[0], (False, None))[0] is False:
        report, stop_reason = handback[1].strip(), "handback"
    p = rules["patterns"]
    t0, t1 = _time(first_ts), _time(last_ts)
    return {
        "session_id": session, "cwd": cwd, "prompt": prompt or "", "model": model,
        "started_at": first_ts, "ended_at": last_ts,
        "duration_s": (t1 - t0).total_seconds() if t0 and t1 else None,
        "stop_reason": stop_reason, "final_report": report,
        "input_tokens": inp, "output_tokens": out, "cache_write_5m": w5, "cache_write_1h": w1, "cache_read": read,
        "weighted_tokens": weighted, "tokens_measured": bool(usage),
        "tool_calls": len(calls), "tool_errors": errors, "redundant_calls": redundant, "repeated_errors": repeated_errors,
        "tool_usage": json.dumps({n: [c, errors_by_tool[n]] for n, c in usage_by_tool.most_common()}, ensure_ascii=False),
        "test_runs": len(tests), "last_test_ok": last(tests),
        "check_runs": len(checks), "last_check_ok": last(checks),
        "regression": regression if tests or checks else 0,
        "criteria": json.dumps(criteria, ensure_ascii=False),
        "claims_done": int(matches(report, p["claims_done"])),
        "claims_tests": int(matches(report, p["claims_tests"])),
        "discloses_unverified": int(matches(report, p["discloses_unverified"])),
        "admits_partial": int(matches(report, p["admits_partial"])),
        "markers": marks,
    }
