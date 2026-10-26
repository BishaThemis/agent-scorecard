"""Run from the plugin folder: python -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
TMP = tempfile.mkdtemp(prefix="agent-scorecard-test-")
os.environ["AGENT_SCORECARD_DATA"] = TMP

from scorecard import classify, config, db, i18n, transcript  # noqa: E402
from scorecard.ingest import ingest, set_vote  # noqa: E402
from scorecard.scoring import _token_points, rescore_all, score  # noqa: E402

RULES = config.rules()


class Transcript:
    """Builds a synthetic subagent transcript."""

    def __init__(self, prompt="Do the task", cwd=None, minute=0):
        self.lines, self.n, self.second = [], 0, minute * 60
        self.cwd = cwd or TMP
        self._add("user", {"role": "user", "content": prompt})

    def _ts(self):
        self.second += 1
        return f"2026-10-01T10:{self.second // 60:02d}:{self.second % 60:02d}.000Z"

    def _add(self, kind, message):
        self.lines.append({"type": kind, "message": message, "timestamp": self._ts(), "cwd": self.cwd,
                           "sessionId": "session-1"})

    def tool(self, name, args, output="ok", error=False, tokens=(100, 50)):
        self.n += 1
        tool_id, msg_id = f"toolu_{self.n}", f"msg_{self.n}"
        usage = {"input_tokens": tokens[0], "output_tokens": tokens[1], "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": 0}
        # One API message split over two lines: usage appears twice and must be counted once
        self._add("assistant", {"id": msg_id, "model": "claude-opus-5-5", "content": [{"type": "thinking"}],
                                "usage": usage, "stop_reason": None})
        self._add("assistant", {"id": msg_id, "model": "claude-opus-5-5", "usage": usage, "stop_reason": "tool_use",
                                "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": args}]})
        self._add("user", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id,
                                                        "content": output, "is_error": error}]})
        return self

    def handback(self, text):
        return self.tool("SubagentHandback", {"message": text}, tokens=(10, 10))

    def write(self, name, finished=True, agent="test-agent", description="task"):
        path = Path(TMP) / f"agent-{name}.jsonl"
        path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in self.lines), encoding="utf-8")
        path.with_name(path.stem + ".meta.json").write_text(
            json.dumps({"agentType": agent, "description": description, "finished": finished}), encoding="utf-8")
        return path


def measure(tr: Transcript):
    return transcript.parse(tr.write("measure"), RULES)


def task(**changes):
    t = {"state": "done", "finished": 1, "stop_reason": "handback", "final_report": "Report.", "criteria": "[]",
         "test_runs": 0, "last_test_ok": None, "check_runs": 0, "last_check_ok": None, "regression": 0,
         "admits_partial": 0, "claims_done": 0, "claims_tests": 0, "discloses_unverified": 0,
         "weighted_tokens": 10000, "tool_calls": 5, "tool_errors": 0, "redundant_calls": 0, "repeated_errors": 0}
    t.update(changes)
    return t


def line(result, section):
    return [x for x in json.loads(result["breakdown"])["lines"] if x["section"] == section][0]


class Measurements(unittest.TestCase):
    def test_tokens_deduplicated_by_message_id(self):
        m = measure(Transcript().tool("Read", {"file_path": "a"}, tokens=(1000, 200)).handback("done"))
        self.assertEqual((m["input_tokens"], m["output_tokens"]), (1010, 210))

    def test_handback_is_the_final_report_and_not_a_tool_call(self):
        m = measure(Transcript().tool("Read", {"file_path": "a"}).handback("Result: 3 files"))
        self.assertEqual((m["final_report"], m["stop_reason"], m["tool_calls"]), ("Result: 3 files", "handback", 1))

    def test_same_input_same_output_is_redundant(self):
        m = measure(Transcript().tool("Read", {"file_path": "a"}, "x").tool("Read", {"file_path": "a"}, "x"))
        self.assertEqual(m["redundant_calls"], 1)

    def test_rereading_after_a_change_is_not_redundant(self):
        m = measure(Transcript().tool("Read", {"file_path": "a"}, "x").tool("Edit", {"file_path": "a"})
                    .tool("Read", {"file_path": "a"}, "x"))
        self.assertEqual(m["redundant_calls"], 0)

    def test_different_output_is_not_redundant(self):
        m = measure(Transcript().tool("Bash", {"command": "ls"}, "a").tool("Bash", {"command": "ls"}, "b"))
        self.assertEqual(m["redundant_calls"], 0)

    def test_rerunning_tests_is_not_penalized(self):
        m = measure(Transcript().tool("Bash", {"command": "pytest"}, "ok").tool("Bash", {"command": "pytest"}, "ok"))
        self.assertEqual((m["redundant_calls"], m["test_runs"]), (0, 2))

    def test_repeating_the_same_error_without_changes(self):
        m = measure(Transcript().tool("Bash", {"command": "npm run x"}, "err", error=True)
                    .tool("Bash", {"command": "npm run x"}, "err", error=True))
        self.assertEqual(m["repeated_errors"], 1)
        self.assertEqual(m["redundant_calls"], 0)   # the same event is not counted in two sections

    def test_fixing_then_retrying_is_not_a_repeated_error(self):
        m = measure(Transcript().tool("Bash", {"command": "pytest"}, "fail", error=True)
                    .tool("Edit", {"file_path": "x.py"}).tool("Bash", {"command": "pytest"}, "ok"))
        self.assertEqual((m["repeated_errors"], m["last_test_ok"], m["regression"]), (0, 1, 0))

    def test_regression(self):
        m = measure(Transcript().tool("Bash", {"command": "pytest"}, "ok").tool("Edit", {"file_path": "x.py"})
                    .tool("Bash", {"command": "pytest"}, "fail", error=True))
        self.assertEqual(m["regression"], 1)

    def test_accept_file_must_be_written_by_the_agent(self):
        (Path(TMP) / "existing.txt").write_text("x")
        (Path(TMP) / "new.txt").write_text("x")
        m = measure(Transcript("Do it\nACCEPT-FILE: existing.txt\nKABUL-DOSYA: new.txt")
                    .tool("Write", {"file_path": "new.txt"}))
        met = {c["value"]: c["met"] for c in json.loads(m["criteria"])}
        self.assertEqual(met, {"existing.txt": False, "new.txt": True})

    def test_markers_in_english_and_turkish(self):
        m = transcript.markers("x\nDIFFICULTY: Hard\nCATEGORY: testing\nTASK-ID: T-12\nACCEPT-CMD: npm test")
        self.assertEqual((m["difficulty"], m["category"], m["task_key"], m["commands"]), ("hard", "testing", "T-12", ["npm test"]))
        m = transcript.markers("x\nZORLUK: kolay\nKATEGORI: hata ayıklama\nGOREV-ID: T-1")
        self.assertEqual((m["difficulty"], m["task_key"]), ("easy", "T-1"))
        self.assertEqual(classify.category("", "", m["category"], RULES), "debugging")

    def test_category_matches_word_starts_only(self):
        self.assertEqual(classify.category("Fix the login crash", "", None, RULES), "debugging")
        self.assertEqual(classify.category("Add prefix option to the API", "", None, RULES), "implementation")


class Scoring(unittest.TestCase):
    def test_token_table(self):
        steps = RULES["tokens"]["steps"]
        for ratio, expected in [(0.4, 20), (0.5, 20), (0.6, 16), (0.8, 10), (1.0, 5), (1.2, 2), (1.5, 0), (3, 0)]:
            self.assertAlmostEqual(_token_points(ratio, steps), expected)
        self.assertAlmostEqual(_token_points(0.7, steps), 13)

    def test_unverified_task_gets_no_success_or_efficiency_points(self):
        r = score(task(), None, [10000] * 5, RULES)
        self.assertEqual((r["outcome"], r["tier"]), ("pending", None))
        for section in ("success", "tokens", "tools"):
            self.assertEqual(line(r, section)["points"], 0)

    def test_unsupported_completion_claim(self):
        self.assertEqual(line(score(task(claims_done=1), None, [], RULES), "reliability")["points"], -15)

    def test_saying_it_was_not_verified_is_not_penalized(self):
        r = score(task(claims_done=1, discloses_unverified=1), None, [], RULES)
        self.assertEqual(line(r, "reliability")["points"], 3)

    def test_false_success_claim_is_penalized_once(self):
        r = score(task(test_runs=1, last_test_ok=0, claims_done=1, claims_tests=1), None, [], RULES)
        self.assertEqual(r["outcome"], "failed")
        lines = json.loads(r["breakdown"])["lines"]
        self.assertEqual(sum(1 for x in lines if x["points"] < 0), 1)
        self.assertEqual(line(r, "false_claim")["points"], -15)
        self.assertEqual(line(r, "reliability")["points"], 0)

    def test_perfect_task_is_diamond(self):
        r = score(task(test_runs=2, last_test_ok=1, criteria=json.dumps([{"met": True, "value": "a"}]),
                       weighted_tokens=5000), None, [10000] * 3, RULES)
        self.assertEqual((r["outcome"], r["score"], r["measurable_max"], r["tier"]), ("success", 100, 100, "diamond"))

    def test_few_tokens_cannot_beat_quality(self):
        """Gaming: leaving work unfinished to spend fewer tokens gives no advantage."""
        cheap = score(task(test_runs=1, last_test_ok=0, weighted_tokens=500), None, [10000] * 3, RULES)
        full = score(task(test_runs=1, last_test_ok=1, weighted_tokens=14000), None, [10000] * 3, RULES)
        self.assertEqual(line(cheap, "tokens")["points"], 0)
        self.assertGreater(full["score"], cheap["score"] + 30)

    def test_too_little_reference_is_marked_unmeasured(self):
        r = score(task(test_runs=1, last_test_ok=1), None, [10000], RULES)
        self.assertFalse(line(r, "tokens")["measured"])
        self.assertEqual(r["measurable_max"], 75)   # tokens 20 + requirements 5 not measured

    def test_admitted_partial(self):
        r = score(task(test_runs=1, last_test_ok=0, admits_partial=1, claims_done=1), None, [], RULES)
        self.assertEqual((r["outcome"], line(r, "success")["points"]), ("partial", 15))
        self.assertNotIn("false_claim", [x["section"] for x in json.loads(r["breakdown"])["lines"]])

    def test_user_vote_decides_the_outcome(self):
        r = score(task(), "success", [], RULES)
        self.assertEqual((r["outcome"], line(r, "requirements")["points"]), ("success", 5))
        self.assertFalse(line(r, "tests")["measured"])   # tests are never granted automatically

    def test_unfinished_task(self):
        r = score(task(finished=0, state="abandoned"), None, [], RULES)
        self.assertEqual((r["outcome"], r["tier"]), ("failed", "none"))


class Translations(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_both_languages_have_the_same_keys(self):
        self.assertEqual(set(i18n.STRINGS["en"]), set(i18n.STRINGS["tr"]))

    def test_every_stored_note_has_a_translation(self):
        r = score(task(test_runs=1, last_test_ok=0, claims_done=1), None, [], RULES)
        b = json.loads(r["breakdown"])
        notes = [b["reason"]] + [x["note"] for x in b["lines"]] + b["reason"]["params"].get("items", [])
        sections = ["section." + x["section"] for x in b["lines"]]
        for key in [n["key"] for n in notes] + sections:
            self.assertIn(key, i18n.STRINGS["en"])

    def test_render_follows_the_language(self):
        n = {"key": "note.tokens_ratio", "params": {"tokens": 12345, "ref": 10000, "n": 4, "ratio": 1.23}}
        self.assertEqual(i18n.render(n), "12,345 weighted tokens; reference 10,000 (4 similar tasks), ratio 1.23.")
        i18n.set_language("tr")
        self.assertEqual(i18n.render(n), "12.345 ağırlıklı token; referans 10.000 (4 benzer görev), oran 1,23.")
        self.assertEqual(i18n.pct(0.79), "%79")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(Path(TMP) / f"{self._testMethodName}.db")

    def _success(self, name, tokens, minute):
        tr = Transcript("Fix the failing test", minute=minute).tool("Bash", {"command": "pytest"}, "ok",
                                                                    tokens=(tokens, 0)).handback("Tests pass")
        ingest(self.con, tr.write(name), RULES)

    def test_reference_only_from_earlier_similar_tasks(self):
        for i, tokens in enumerate([10000, 10000, 10000, 5000]):
            self._success(f"r{i}", tokens, minute=i)
        rescore_all(self.con, RULES)
        scores = [r["score"] for r in self.con.execute("SELECT score FROM tasks ORDER BY agent_id")]
        # The first three have no reference; the fourth uses half the tokens and gets full token points
        self.assertEqual(scores, [75.0, 75.0, 75.0, 95.0])

    def test_vote_rescores(self):
        tr = Transcript("Research something").tool("Read", {"file_path": "a"}).handback("Findings here, not tested")
        ingest(self.con, tr.write("vote"), RULES)
        rescore_all(self.con, RULES)
        self.assertEqual(self.con.execute("SELECT outcome FROM tasks").fetchone()[0], "pending")
        set_vote(self.con, "vote", "success", RULES)
        self.assertEqual(self.con.execute("SELECT outcome FROM tasks").fetchone()[0], "success")

    def _hook(self, stdin: str):
        return subprocess.run([sys.executable, str(SCRIPTS / "hook.py")], input=stdin, capture_output=True,
                              text=True, env={**os.environ, "AGENT_SCORECARD_DATA": TMP})

    def test_hook_subagent_stop(self):
        path = Transcript().tool("Bash", {"command": "pytest"}).handback("ok").write("hook")
        result = self._hook(json.dumps({"hook_event_name": "SubagentStop", "agent_id": "hook",
                                        "agent_transcript_path": str(path)}))
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        row = db.connect().execute("SELECT outcome, stop_event FROM tasks WHERE agent_id='hook'").fetchone()
        self.assertEqual(tuple(row), ("success", 1))

    def test_hook_never_blocks_claude_on_bad_input(self):
        self.assertEqual(self._hook("{broken").returncode, 0)


if __name__ == "__main__":
    unittest.main()
