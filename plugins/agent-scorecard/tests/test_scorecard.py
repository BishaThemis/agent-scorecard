"""Run from the plugin folder: python -m unittest discover -s tests"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
TMP = tempfile.mkdtemp(prefix="agent-scorecard-test-")
os.environ["AGENT_SCORECARD_DATA"] = TMP

from scorecard import classify, config, db, export, history, i18n, icon, metrics, shortcut, transcript  # noqa: E402
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
                              text=True, env={**os.environ, "AGENT_SCORECARD_DATA": TMP},
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_hook_subagent_stop(self):
        path = Transcript().tool("Bash", {"command": "pytest"}).handback("ok").write("hook")
        result = self._hook(json.dumps({"hook_event_name": "SubagentStop", "agent_id": "hook",
                                        "agent_transcript_path": str(path)}))
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        row = db.connect().execute("SELECT outcome, stop_event FROM tasks WHERE agent_id='hook'").fetchone()
        self.assertEqual(tuple(row), ("success", 1))

    def test_hook_never_blocks_claude_on_bad_input(self):
        self.assertEqual(self._hook("{broken").returncode, 0)


class PhaseOne(unittest.TestCase):
    """Append-only history, career points and levels, task groups, summaries, export."""

    def setUp(self):
        self.con = db.connect(Path(TMP) / f"p1-{self._testMethodName}.db")

    def _task(self, name, agent="a", minute=0, ok=True, prompt="Fix the failing test", description="task"):
        tr = Transcript(prompt, minute=minute).tool("Bash", {"command": "pytest"}, "out", error=not ok).handback("Report")
        ingest(self.con, tr.write(name, agent=agent, description=description), RULES)

    def _scored(self, *tasks):
        for i, (name, agent, ok) in enumerate(tasks):
            self._task(name, agent, minute=i, ok=ok)
        rescore_all(self.con, RULES)

    def test_scores_are_logged_and_the_chain_verifies(self):
        self._scored(("t1", "a", True), ("t2", "a", False))
        kinds = [r["kind"] for r in self.con.execute("SELECT kind FROM events ORDER BY seq")]
        self.assertEqual(kinds, ["scored", "scored"])
        self.assertTrue(history.verify(self.con)["ok"])
        rescore_all(self.con, RULES)   # nothing changed: nothing new is logged
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM events").fetchone()[0], 2)

    def test_events_and_tasks_cannot_be_rewritten(self):
        self._scored(("t1", "a", True))
        for sql in ("UPDATE events SET data='{}'", "DELETE FROM events", "DELETE FROM tasks"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                self.con.execute(sql)
        self.con.rollback()

    def test_tampering_is_detected(self):
        self._scored(("t1", "a", True), ("t2", "a", True))
        self.con.execute("DROP TRIGGER events_no_update")
        self.con.execute("UPDATE events SET data=replace(data, '\"delta\": 75', '\"delta\": 99') WHERE seq=1")
        self.con.commit()
        self.assertEqual(history.verify(self.con)["problem"], "modified")

    def test_cutting_the_end_of_the_log_is_detected(self):
        self._scored(("t1", "a", True), ("t2", "a", True))
        self.con.execute("DROP TRIGGER events_no_delete")
        self.con.execute("DELETE FROM events WHERE seq=2")
        self.con.commit()
        self.assertEqual(history.verify(self.con)["problem"], "truncated")

    def test_removed_tasks_are_detected(self):
        self._scored(("t1", "a", True))
        self.con.execute("DROP TRIGGER tasks_no_delete")
        self.con.execute("DELETE FROM tasks")
        self.con.commit()
        self.assertEqual(history.verify(self.con)["missing_tasks"], 1)

    def test_vote_changes_are_logged_as_deltas(self):
        self._scored(("t1", "a", True))
        before = history.career_points(self.con)["a"]
        set_vote(self.con, "t1", "failed", RULES)
        set_vote(self.con, "t1", "failed", RULES)   # same vote again: no new events
        set_vote(self.con, "t1", None, RULES)
        kinds = [r["kind"] for r in self.con.execute("SELECT kind FROM events ORDER BY seq")]
        self.assertEqual(kinds, ["scored", "vote", "rescored", "vote", "rescored"])
        self.assertAlmostEqual(history.career_points(self.con)["a"], before)
        self.assertTrue(history.verify(self.con)["ok"])

    def test_side_effects_of_a_vote_get_their_own_reason(self):
        self._task("r0", "a", minute=0)
        self._task("r1", "a", minute=1)
        unverified = Transcript("Fix the failing test", minute=2).tool("Read", {"file_path": "x"}).handback("Report")
        ingest(self.con, unverified.write("p", agent="b"), RULES)
        self._task("later", "c", minute=5)
        rescore_all(self.con, RULES)
        set_vote(self.con, "p", "success", RULES)   # p becomes the 3rd reference for "later"
        reasons = {r["agent_id"]: json.loads(r["data"])["reason"]
                   for r in self.con.execute("SELECT agent_id, data FROM events WHERE seq > 3 AND kind != 'vote'")}
        self.assertEqual(reasons, {"p": "vote", "later": "reference_changed"})

    def test_career_points_equal_the_sum_of_final_scores(self):
        self._scored(("t1", "a", True), ("t2", "a", False), ("t3", "b", True))
        totals = {r["agent_type"]: r["s"] for r in self.con.execute(
            "SELECT agent_type, SUM(score) s FROM tasks WHERE outcome IN ('success','partial','failed') GROUP BY 1")}
        career = history.career_points(self.con)
        for agent, total in totals.items():
            self.assertAlmostEqual(career[agent], total)

    def test_levels_never_change_task_scores(self):
        for i in range(3):
            self._task(f"history{i}", "veteran", minute=i)
        self._task("veteran-now", "veteran", minute=10)
        self._task("newcomer-now", "newcomer", minute=10)
        rescore_all(self.con, RULES)
        scores = dict(self.con.execute("SELECT agent_id, score FROM tasks WHERE agent_id LIKE '%-now'").fetchall())
        self.assertGreater(history.career_points(self.con)["veteran"], history.career_points(self.con)["newcomer"])
        self.assertEqual(scores["veteran-now"], scores["newcomer-now"])

    def test_level_thresholds(self):
        self.assertEqual(metrics.level_of(0, RULES)["key"], "novice")
        self.assertEqual(metrics.level_of(-20, RULES)["key"], "novice")
        lv = metrics.level_of(650, RULES)
        self.assertEqual((lv["key"], lv["next_key"], round(lv["progress"], 2)), ("apprentice", "expert", 0.5))
        self.assertIsNone(metrics.level_of(50000, RULES)["next_key"])

    def test_score_records_rules_and_references(self):
        for i in range(4):
            self._task(f"r{i}", minute=i)
        rescore_all(self.con, RULES)
        row = self.con.execute("SELECT rules_hash, reference_ids FROM tasks WHERE agent_id='r3'").fetchone()
        self.assertEqual(row["rules_hash"], config.rules_hash(RULES))
        self.assertEqual(json.loads(row["reference_ids"]), ["r0", "r1", "r2"])

    def test_task_groups_sum_every_agent(self):
        self._task("g1", "a", minute=0, ok=False, prompt="Fix it\nTASK-ID: BUG-1")
        self._task("g2", "b", minute=1, prompt="Fix it\nTASK-ID: BUG-1")
        self._task("g3", "a", minute=2, description="Write docs")
        self._task("g4", "c", minute=3, description="Write docs")
        rescore_all(self.con, RULES)
        groups = {g["label"]: g for g in metrics.task_groups(self.con)}
        costs = dict(self.con.execute("SELECT agent_id, cost_usd FROM tasks").fetchall())
        bug = groups["BUG-1"]
        self.assertEqual((bug["exact"], bug["attempts"], bug["agents"], bug["first_outcome"], bug["outcome"]),
                         (True, 2, ["a", "b"], "failed", "success"))
        self.assertAlmostEqual(bug["cost"], costs["g1"] + costs["g2"])
        self.assertEqual((groups["Write docs"]["exact"], groups["Write docs"]["attempts"]), (False, 2))
        s = metrics.success_metrics(self.con)
        self.assertEqual((s["groups"], s["first_attempt"]), (2, 0.5))

    def test_period_summary(self):
        self._scored(("t1", "a", True))
        days = metrics.period_summary(self.con, "day", 14)
        weeks = metrics.period_summary(self.con, "week", 8)
        self.assertEqual((len(days), len(weeks)), (14, 8))
        self.assertTrue(all(w["start"].weekday() == 0 for w in weeks))

    def test_profile(self):
        self._scored(("t1", "a", True), ("t2", "a", False))
        p = metrics.agent_profile(self.con, "a", RULES)
        self.assertEqual((p["final"], p["counts"]["success"], p["counts"]["failed"], len(p["failures"])), (2, 1, 1, 1))
        self.assertEqual(p["tools"][0][0], "Bash")
        self.assertGreater(p["gained"], 0)
        self.assertEqual(len(p["weeks"]), 8)

    def test_export(self):
        self._scored(("t1", "a", True), ("t2", "b", False))
        n = export.export_csv(self.con, Path(TMP) / "out.csv")
        with open(Path(TMP) / "out.csv", encoding="utf-8-sig") as f:
            header = f.readline()
        self.assertEqual(n, 2)
        self.assertIn("agent_type", header)
        self.assertNotIn("final_report", header)
        export.export_json(self.con, Path(TMP) / "out.json", RULES)
        data = json.loads((Path(TMP) / "out.json").read_text(encoding="utf-8"))
        self.assertEqual((len(data["tasks"]), len(data["events"]), data["chain"]["ok"]), (2, 2, True))

    def test_old_database_is_migrated(self):
        path = Path(TMP) / "old.db"
        old = sqlite3.connect(path)
        v010_tasks = db.SCHEMA.split(");")[0].replace(" rules_hash TEXT, reference_ids TEXT,", "") + ");"
        self.assertNotIn("rules_hash", v010_tasks)
        old.execute(v010_tasks)
        old.execute("INSERT INTO tasks (agent_id, agent_type) VALUES ('x', 'a')")
        old.commit()
        old.close()
        cols = {r["name"] for r in db.connect(path).execute("PRAGMA table_info(tasks)")}
        self.assertTrue({"rules_hash", "reference_ids"} <= cols)


class DesktopShortcut(unittest.TestCase):
    def test_icon_files_are_valid(self):
        data = icon.png(32)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        path = Path(TMP) / "test.ico"
        icon.write_ico(path)
        head = path.read_bytes()[:6]
        self.assertEqual(head, b"\x00\x00\x01\x00" + bytes([len(icon.SIZES), 0]))

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_shortcut_points_to_a_stable_launcher(self):
        desktop = Path(TMP) / "fake-desktop"
        desktop.mkdir(exist_ok=True)
        link = shortcut.create(SCRIPTS, desktop=desktop)
        self.assertEqual(link, desktop / "Agent Scorecard.lnk")
        self.assertTrue(link.exists())
        launcher = config.data_dir() / "Agent Scorecard.pyw"
        self.assertIn("plugin_root.txt", launcher.read_text(encoding="utf-8"))
        root = (config.data_dir() / "plugin_root.txt").read_text(encoding="utf-8")
        self.assertTrue((Path(root) / "dashboard.pyw").exists())


if __name__ == "__main__":
    unittest.main()
