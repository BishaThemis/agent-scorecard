"""Generates fictional subagent transcripts for trying the dashboard without real data.

    python tools/make_demo.py <demo-folder>

Then point the dashboard at it:
    set CLAUDE_CONFIG_DIR=<demo-folder>\\claude
    set AGENT_SCORECARD_DATA=<demo-folder>\\data
    python plugins/agent-scorecard/scripts/dashboard.pyw
"""
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENTS = {
    "frontend-developer": [("Add dark mode toggle to settings page", "implementation"),
                           ("Build pricing table component", "implementation"),
                           ("Fix layout shift on product page", "debugging")],
    "test-writer": [("Write unit tests for cart totals", "testing"), ("Add tests for date parsing", "testing")],
    "debugger": [("Fix crash when uploading empty file", "debugging"), ("Fix flaky checkout test", "debugging")],
    "code-reviewer": [("Review payment refactor", "review"), ("Audit auth middleware", "review")],
    "researcher": [("Compare three charting libraries", "research"), ("Investigate slow search queries", "research")],
}
# outcome: (tests run?, last test ok?, report)
PROFILES = {
    "frontend-developer": [0.75, 0.1, 0.15],  # success, partial, failed (others pending)
    "test-writer": [0.9, 0.05, 0.05],
    "debugger": [0.6, 0.15, 0.25],
    "code-reviewer": [0.0, 0.0, 0.0],
    "researcher": [0.0, 0.0, 0.1],
}


def write_task(root: Path, n: int, agent: str, description: str, start: datetime, rnd: random.Random,
               running: bool = False):
    session = f"demo-session-{n // 4}"
    folder = root / "projects" / "demo-shop" / session / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    lines, clock, call = [], [start], [0]

    def ts():
        clock[0] += timedelta(seconds=rnd.randint(4, 40))
        return clock[0].isoformat().replace("+00:00", "Z")

    def add(kind, message):
        lines.append({"type": kind, "message": message, "timestamp": ts(), "cwd": "C:/demo/demo-shop",
                      "sessionId": session})

    def tool(name, args, error=False, output="ok"):
        call[0] += 1
        usage = {"input_tokens": rnd.randint(200, 900), "output_tokens": rnd.randint(150, 1600),
                 "cache_read_input_tokens": rnd.randint(8000, 30000), "cache_creation_input_tokens": rnd.randint(0, 3000)}
        add("assistant", {"id": f"m{call[0]}", "model": rnd.choice(["claude-opus-5-5", "claude-sonnet-5-5"]),
                          "usage": usage, "stop_reason": "tool_use",
                          "content": [{"type": "tool_use", "id": f"t{call[0]}", "name": name, "input": args}]})
        add("user", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{call[0]}",
                                                  "content": output, "is_error": error}]})

    add("user", {"role": "user", "content": f"{description}.\nKeep the change focused."})
    p_success, p_partial, p_failed = PROFILES[agent]
    roll = rnd.random()
    outcome = ("success" if roll < p_success else "partial" if roll < p_success + p_partial
               else "failed" if roll < p_success + p_partial + p_failed else "pending")
    for _ in range(rnd.randint(4, 14)):
        tool(rnd.choice(["Read", "Grep", "Glob"]), {"file_path": f"src/file{rnd.randint(1, 30)}.ts"},
             output=f"content {rnd.randint(1, 3)}")
    if rnd.random() < 0.3:
        tool("Read", {"file_path": "src/same.ts"}, output="same")
        tool("Read", {"file_path": "src/same.ts"}, output="same")      # a redundant repeat
    if outcome != "pending" or agent in ("frontend-developer", "debugger"):
        tool("Edit", {"file_path": f"src/file{rnd.randint(1, 30)}.ts"})
    if rnd.random() < 0.2:
        tool("Bash", {"command": "npm run migrate"}, error=True, output="error")
        tool("Bash", {"command": "npm run migrate"}, error=True, output="error")  # a repeated error
    if outcome in ("success", "partial", "failed") and agent not in ("code-reviewer", "researcher"):
        tool("Bash", {"command": "npm test"}, error=outcome == "failed", output="tests")
    report = {"success": "Done. All tests pass.", "partial": "Partially done: I could not update the e2e snapshots.",
              "failed": "Completed the change.", "pending": "Findings: see the summary below. Not verified."}[outcome]
    if not running:
        call[0] += 1
        add("assistant", {"id": f"m{call[0]}", "model": "claude-sonnet-5-5", "stop_reason": "tool_use",
                          "usage": {"input_tokens": 50, "output_tokens": 120},
                          "content": [{"type": "tool_use", "id": f"t{call[0]}", "name": "SubagentHandback",
                                       "input": {"message": report}}]})
        add("user", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{call[0]}",
                                                  "content": "ok"}]})
    path = folder / f"agent-demo{n:03d}.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    (folder / f"agent-demo{n:03d}.meta.json").write_text(
        json.dumps({"agentType": agent, "description": description, "finished": not running}), encoding="utf-8")
    if not running:
        old = time.time() - 3600
        os.utime(path, (old, old))


def main(target: str):
    root = Path(target) / "claude"
    rnd = random.Random(7)
    now = datetime.now(timezone.utc)
    n = 0
    for day in range(13, -1, -1):
        for _ in range(rnd.randint(2, 4)):
            agent = rnd.choice(list(AGENTS))
            description, _ = rnd.choice(AGENTS[agent])
            write_task(root, n, agent, description, now - timedelta(days=day, hours=rnd.randint(1, 10)), rnd)
            n += 1
    write_task(root, n, "frontend-developer", "Add CSV export to orders page", now - timedelta(minutes=4), rnd,
               running=True)
    print(f"{n + 1} demo transcripts written to {root}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo")
