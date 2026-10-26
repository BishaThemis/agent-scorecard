"""Claude Code hook entry point: SubagentStart, SubagentStop and (optional) SessionStart.

Never blocks Claude: errors go to the log file and the exit code is always 0.
Writes to stdout only on SessionStart, and only if the user turned on routing hints.
"""
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scorecard import config, db, i18n, metrics  # noqa: E402
from scorecard.ingest import ingest, record_start  # noqa: E402
from scorecard.scoring import rescore_all  # noqa: E402


def _transcript_path(data: dict) -> Path | None:
    if data.get("agent_transcript_path"):
        return Path(data["agent_transcript_path"])
    if data.get("transcript_path") and data.get("agent_id"):
        return Path(data["transcript_path"]).with_suffix("") / "subagents" / f"agent-{data['agent_id']}.jsonl"
    return None


def _hint(con, rules) -> str:
    lines = []
    for r in metrics.routing(con, rules["routing"]["min_tasks"]):
        if r["best"]:
            b = r["best"]
            lines.append(i18n.t("hint.line", cat=i18n.t(f"cat.{r['category']}"), diff=i18n.t(f"diff.{r['difficulty']}"),
                                agent=b["agent"], score=i18n.num(b["mean_score"]), rate=i18n.pct(b["success"]), n=b["n"]))
    return i18n.t("hint.header") + "\n" + "\n".join(lines[:12]) if lines else ""


def main() -> None:
    data = json.loads(sys.stdin.read() or "{}")
    event = data.get("hook_event_name")
    rules = config.rules()
    con = db.connect()
    try:
        if event == "SubagentStart" and data.get("agent_id"):
            record_start(con, data["agent_id"], data.get("agent_type"), data.get("session_id"))
        elif event == "SubagentStop":
            path = _transcript_path(data)
            if path and path.exists() and ingest(con, path, rules, force=True, stopped=True):
                rescore_all(con, rules)
        elif event == "SessionStart" and rules["routing"]["session_start_hint"]:
            i18n.load_language()
            text = _hint(con, rules)
            if text:
                print(text)
        con.commit()
    finally:
        con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            with open(config.data_dir() / "hook.log", "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now().isoformat()}\n{traceback.format_exc()}\n")
        except Exception:
            pass
    sys.exit(0)
