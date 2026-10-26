"""Agent Scorecard desktop dashboard (tkinter, no extra dependencies)."""
import json
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scorecard import config, db, export, history, i18n, metrics  # noqa: E402
from scorecard.i18n import num, pct, render, t  # noqa: E402
from scorecard.ingest import scan, set_vote  # noqa: E402

COLOR = {
    "bg": "#f4f5f7", "card": "#ffffff", "text": "#1d2330", "muted": "#6b7280", "line": "#e3e5ea",
    "accent": "#3b5bdb", "good": "#2b8a3e", "bad": "#c92a2a", "warn": "#e67700",
    "diamond": "#1c7ed6", "gold": "#b08800", "silver": "#868e96", "bronze": "#a9652b",
}
OUTCOME_COLOR = {"success": "text", "partial": "warn", "failed": "bad", "pending": "muted", "running": "accent"}
OUTCOMES = ("success", "partial", "failed", "pending", "running")
TIER_MARK = {"diamond": "◆", "gold": "★", "silver": "●", "bronze": "▲"}
FONT = "Segoe UI"
TAB_TASKS, TAB_PROFILE = 1, 4


def duration(seconds):
    if seconds is None:
        return "—"
    s = int(seconds)
    return t("dur.h", h=s // 3600, m=s % 3600 // 60) if s >= 3600 else t("dur.m", m=s // 60, s=s % 60)


def local(ts, fmt="%d.%m %H:%M"):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime(fmt)
    except (AttributeError, ValueError):
        return "—"


def tier_label(tier):
    if not tier:
        return "—"
    return f"{TIER_MARK[tier]} {t('tier.' + tier)}" if tier in TIER_MARK else t("tier." + tier)


def outcome_label(outcome):
    return t("outcome." + outcome) if outcome else "—"


def money(value, decimals=2):
    return "—" if value is None else "$" + num(value, decimals)


class Scanner(threading.Thread):
    """Scans transcripts in the background so the window never freezes."""

    def __init__(self):
        super().__init__(daemon=True)
        self.version = 0
        self.last = None
        self.error = None

    def run(self):
        con = db.connect()
        last_full = 0.0
        while True:
            try:
                rules = config.rules()
                full = time.time() - last_full > 20
                changed = scan(con, rules, running_only=not full)
                if full:
                    last_full = time.time()
                if changed or full:
                    self.version += 1
                self.last, self.error = datetime.now(), None
            except Exception as e:  # a scan error must not close the dashboard
                self.error = str(e)
            time.sleep(3)


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        i18n.load_language()
        self.geometry("1360x820")
        self.minsize(1000, 640)
        self.configure(bg=COLOR["bg"])
        self.con = db.connect()
        self.rules = config.rules()
        self.scanner = Scanner()
        self.seen_version = -1
        self.agent_filter = None          # None = all
        self.outcome_filter = None
        self.profile_agent = None
        self.chain = {"ok": True}
        self.notice = None
        self._style()
        self.frame = None
        self._build()
        self.scanner.start()
        self.after(300, self._loop)

    # ---------- layout ----------
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", font=(FONT, 10), background=COLOR["bg"], foreground=COLOR["text"])
        s.configure("TNotebook", background=COLOR["bg"], borderwidth=0)
        s.configure("TNotebook.Tab", padding=(14, 7), font=(FONT, 10), background=COLOR["line"])
        s.map("TNotebook.Tab", background=[("selected", COLOR["card"])])
        s.configure("Treeview", rowheight=26, background=COLOR["card"], fieldbackground=COLOR["card"],
                    bordercolor=COLOR["line"])
        s.configure("Treeview.Heading", font=(FONT, 9, "bold"), background=COLOR["bg"],
                    foreground=COLOR["muted"], relief="flat")
        s.map("Treeview", background=[("selected", "#dbe4ff")], foreground=[("selected", COLOR["text"])])
        s.configure("Card.TFrame", background=COLOR["card"])
        s.configure("TButton", padding=(10, 4))

    def _build(self):
        if self.frame:
            self.frame.destroy()
        self.title(t("app.title"))
        self.frame = root = tk.Frame(self, bg=COLOR["bg"])
        root.pack(fill="both", expand=True)

        top = tk.Frame(root, bg=COLOR["bg"])
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text=t("app.title"), font=(FONT, 17, "bold"), bg=COLOR["bg"], fg=COLOR["text"]).pack(side="left")
        tk.Label(top, text="  " + t("app.subtitle"), font=(FONT, 10), bg=COLOR["bg"],
                 fg=COLOR["muted"]).pack(side="left", pady=(6, 0))
        self.lang = ttk.Combobox(top, state="readonly", width=10, values=list(i18n.LANGUAGES.values()))
        self.lang.set(i18n.LANGUAGES[i18n.language()])
        self.lang.pack(side="right")
        self.lang.bind("<<ComboboxSelected>>", self._change_language)
        tk.Label(top, text=t("lang.label"), bg=COLOR["bg"], fg=COLOR["muted"]).pack(side="right", padx=6)

        self.cards = {}
        row = tk.Frame(root, bg=COLOR["bg"])
        row.pack(fill="x", padx=12)
        for i, key in enumerate(["first_attempt", "tokens", "cost", "duration", "problems", "tasks"]):
            card = tk.Frame(row, bg=COLOR["card"], highlightbackground=COLOR["line"], highlightthickness=1)
            card.grid(row=0, column=i, sticky="nsew", padx=4, pady=4)
            row.columnconfigure(i, weight=1)
            tk.Label(card, text=t("card." + key), font=(FONT, 9), bg=COLOR["card"],
                     fg=COLOR["muted"]).pack(anchor="w", padx=12, pady=(9, 0))
            value = tk.Label(card, text="—", font=(FONT, 16, "bold"), bg=COLOR["card"], fg=COLOR["text"])
            value.pack(anchor="w", padx=12)
            delta = tk.Label(card, text="", font=(FONT, 9), bg=COLOR["card"], fg=COLOR["muted"])
            delta.pack(anchor="w", padx=12, pady=(0, 9))
            self.cards[key] = (value, delta)

        self.book = ttk.Notebook(root)
        self.book.pack(fill="both", expand=True, padx=16, pady=(8, 4))
        self._live_tab()
        self._tasks_tab()
        self._groups_tab()
        self._agents_tab()
        self._profile_tab()
        self._summary_tab()
        self._routing_tab()
        self._history_tab()

        self.status = tk.Label(root, text=t("status.first"), anchor="w", font=(FONT, 9),
                               bg=COLOR["bg"], fg=COLOR["muted"])
        self.status.pack(fill="x", padx=18, pady=(0, 8))

    def _change_language(self, _event):
        code = next(c for c, name in i18n.LANGUAGES.items() if name == self.lang.get())
        if code == i18n.language():
            return
        config.save_setting("language", code)
        i18n.set_language(code)
        tab = self.book.index("current")
        self._build()
        self.book.select(tab)
        self.refresh()

    def _tab(self, key):
        f = ttk.Frame(self.book, padding=10)
        self.book.add(f, text=f"  {t(key)}  ")
        return f

    def _hint(self, parent, text):
        tk.Label(parent, text=text, bg=COLOR["bg"], fg=COLOR["muted"], anchor="w", justify="left",
                 wraplength=1250).pack(fill="x", pady=(0, 6))

    def _table(self, parent, columns, height=None):
        frame = ttk.Frame(parent, style="Card.TFrame")
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse",
                            **({"height": height} if height else {}))
        for name, title, width, anchor in columns:
            tree.heading(name, text=t(title))
            tree.column(name, width=width, anchor=anchor, stretch=name in ("task", "suggested", "label"))
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        for name, color in COLOR.items():
            tree.tag_configure(name, foreground=color)
        return frame, tree

    def _text(self, parent):
        box = tk.Text(parent, wrap="word", font=(FONT, 10), relief="flat", bg=COLOR["card"], fg=COLOR["text"],
                      padx=8, pady=8, height=10)
        for name, color in COLOR.items():
            box.tag_configure(name, foreground=color)
        box.tag_configure("title", font=(FONT, 12, "bold"))
        box.tag_configure("bold", font=(FONT, 10, "bold"))
        box.tag_configure("small", font=(FONT, 9), foreground=COLOR["muted"])
        box.configure(state="disabled")
        return box

    def _place_sash(self, pane, share=0.63):
        """Puts a divider at `share` of the width once the pane has its real width."""
        if not pane.winfo_exists():
            return
        if pane.winfo_width() < 300:
            self.after(150, lambda: self._place_sash(pane, share))
        else:
            pane.sashpos(0, int(pane.winfo_width() * share))

    def _live_tab(self):
        f = self._tab("tab.live")
        self.live_info = tk.Label(f, text="", font=(FONT, 10), bg=COLOR["bg"], fg=COLOR["muted"], anchor="w")
        self.live_info.pack(fill="x", pady=(0, 6))
        frame, self.live = self._table(f, [
            ("agent", "col.agent", 190, "w"), ("task", "col.task", 360, "w"), ("project", "col.project", 140, "w"),
            ("elapsed", "col.elapsed", 90, "e"), ("tokens", "col.weighted", 120, "e"),
            ("calls", "col.calls", 100, "e"), ("errors", "col.errors", 60, "e"), ("model", "col.model", 140, "w")])
        frame.pack(fill="both", expand=True)

    def _tasks_tab(self):
        f = self._tab("tab.tasks")
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text=t("filter.agent")).pack(side="left")
        self.f_agent = ttk.Combobox(bar, state="readonly", width=28)
        self.f_agent.pack(side="left", padx=(4, 12))
        ttk.Label(bar, text=t("filter.outcome")).pack(side="left")
        self.f_outcome = ttk.Combobox(bar, state="readonly", width=22,
                                      values=[t("filter.all")] + [t("outcome." + o) for o in OUTCOMES])
        self.f_outcome.set(t("outcome." + self.outcome_filter) if self.outcome_filter else t("filter.all"))
        self.f_outcome.pack(side="left", padx=4)
        self.f_agent.bind("<<ComboboxSelected>>", self._filters_changed)
        self.f_outcome.bind("<<ComboboxSelected>>", self._filters_changed)
        ttk.Button(bar, text=t("export.json"), command=lambda: self._export("json")).pack(side="right")
        ttk.Button(bar, text=t("export.csv"), command=lambda: self._export("csv")).pack(side="right", padx=4)

        pane = ttk.PanedWindow(f, orient="horizontal")
        pane.pack(fill="both", expand=True)
        self._place_sash(pane)
        left, self.tasks = self._table(pane, [
            ("started", "col.started", 82, "w"), ("agent", "col.agent", 140, "w"), ("task", "col.task", 200, "w"),
            ("outcome", "col.outcome", 140, "w"), ("score", "col.score", 58, "e"), ("tier", "col.reward", 88, "w"),
            ("tokens", "col.tokens", 82, "e"), ("cost", "col.cost", 62, "e")])
        pane.add(left, weight=3)
        self.tasks.bind("<<TreeviewSelect>>", lambda e: self._show_detail())

        right = ttk.Frame(pane, style="Card.TFrame", padding=10)
        pane.add(right, weight=2)
        buttons = ttk.Frame(right, style="Card.TFrame")
        buttons.pack(fill="x")
        tk.Label(buttons, text=t("verify.label"), bg=COLOR["card"], fg=COLOR["muted"]).pack(side="left")
        for key, vote in (("verify.success", "success"), ("verify.partial", "partial"), ("verify.failed", "failed"),
                          ("verify.clear", None)):
            ttk.Button(buttons, text=t(key), command=lambda v=vote: self._vote(v)).pack(side="left", padx=2)
        self.detail = self._text(right)
        self.detail.pack(fill="both", expand=True, pady=(8, 0))

    def _groups_tab(self):
        f = self._tab("tab.groups")
        self._hint(f, t("groups.hint"))
        frame, self.groups = self._table(f, [
            ("started", "col.started", 82, "w"), ("label", "col.task", 260, "w"), ("match", "col.match", 130, "w"),
            ("attempts", "col.attempts", 70, "e"), ("agents", "col.agents", 220, "w"),
            ("first", "col.first", 140, "w"), ("final", "col.final", 140, "w"),
            ("tokens", "col.tokens", 90, "e"), ("cost", "col.cost", 110, "e")])
        frame.pack(fill="both", expand=True)

    def _agents_tab(self):
        f = self._tab("tab.agents")
        self._hint(f, t("agents.hint"))
        frame, self.agents = self._table(f, [
            ("agent", "col.agent", 190, "w"), ("level", "col.level", 100, "w"), ("career", "col.career", 110, "e"),
            ("mean", "col.mean", 80, "e"), ("success", "col.success", 70, "e"), ("tasks", "col.ntasks", 60, "e"),
            ("pending", "col.pending", 140, "e"), ("diamond", "tier.diamond", 64, "e"), ("gold", "tier.gold", 56, "e"),
            ("silver", "tier.silver", 60, "e"), ("bronze", "tier.bronze", 60, "e"),
            ("tokens", "col.tok_success", 160, "e"), ("cost", "col.total_cost", 100, "e"),
            ("flagged", "col.flagged", 80, "e")])
        frame.pack(fill="both", expand=True)
        self.agents.bind("<Double-1>", self._open_profile)

    def _profile_tab(self):
        f = self._tab("tab.profile")
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text=t("profile.agent")).pack(side="left")
        self.p_agent = ttk.Combobox(bar, state="readonly", width=30)
        self.p_agent.pack(side="left", padx=(4, 8))
        self.p_agent.bind("<<ComboboxSelected>>", lambda e: self._select_profile(self.p_agent.get()))
        ttk.Button(bar, text=t("profile.show_tasks"), command=self._profile_tasks).pack(side="left")

        pane = ttk.PanedWindow(f, orient="horizontal")
        pane.pack(fill="both", expand=True)
        self._place_sash(pane, 0.5)
        self.p_text = self._text(pane)
        pane.add(self.p_text, weight=1)
        right = ttk.Frame(pane, style="Card.TFrame", padding=10)
        pane.add(right, weight=1)
        tk.Label(right, text=t("profile.trend_h"), font=(FONT, 10, "bold"), bg=COLOR["card"], fg=COLOR["text"],
                 anchor="w", wraplength=560, justify="left").pack(fill="x")
        self.p_chart = tk.Canvas(right, height=190, bg=COLOR["card"], highlightthickness=0)
        self.p_chart.pack(fill="x", pady=(4, 10))
        self.p_chart.bind("<Configure>", lambda e: self._draw_trend())
        tk.Label(right, text=t("profile.categories_h"), font=(FONT, 10, "bold"), bg=COLOR["card"], fg=COLOR["text"],
                 anchor="w").pack(fill="x")
        frame, self.p_cats = self._table(right, [
            ("category", "col.category", 130, "w"), ("difficulty", "col.difficulty", 80, "w"),
            ("n", "col.ntasks", 60, "e"), ("success", "col.success", 70, "e"), ("mean", "col.mean", 80, "e"),
            ("reliable", "col.reliable", 80, "w")], height=6)
        frame.pack(fill="both", expand=True)
        self.p_weeks = []

    def _summary_tab(self):
        f = self._tab("tab.summary")
        columns = [("period", "col.period", 140, "w"), ("tasks", "col.ntasks", 60, "e"),
                   ("success", "col.success", 70, "e"), ("first", "col.first_attempt", 90, "e"),
                   ("tokens", "col.tok_per_success", 120, "e"), ("cost", "col.cost_per_task", 110, "e"),
                   ("time", "col.avg_time", 110, "e"), ("tests", "col.test_pass", 100, "e"),
                   ("problems", "col.problems", 190, "e")]
        tk.Label(f, text=t("summary.daily"), font=(FONT, 10, "bold"), bg=COLOR["bg"], anchor="w").pack(fill="x")
        frame, self.daily = self._table(f, columns, height=8)
        frame.pack(fill="both", expand=True, pady=(2, 10))
        tk.Label(f, text=t("summary.weekly"), font=(FONT, 10, "bold"), bg=COLOR["bg"], anchor="w").pack(fill="x")
        frame, self.weekly = self._table(f, columns, height=8)
        frame.pack(fill="both", expand=True, pady=(2, 0))

    def _routing_tab(self):
        f = self._tab("tab.routing")
        self._hint(f, t("routing.hint", n=self.rules["routing"]["min_tasks"]))
        frame, self.routing = self._table(f, [
            ("category", "col.category", 150, "w"), ("difficulty", "col.difficulty", 80, "w"),
            ("suggested", "col.suggested", 220, "w"), ("score", "col.mean", 80, "e"),
            ("success", "col.success", 70, "e"), ("tokens", "col.mean_tokens", 110, "e"),
            ("runner", "col.runner_up", 200, "w"), ("data", "col.data", 140, "w")])
        frame.pack(fill="both", expand=True)

    def _history_tab(self):
        f = self._tab("tab.history")
        self.chain_label = tk.Label(f, text="", font=(FONT, 10, "bold"), bg=COLOR["bg"], anchor="w")
        self.chain_label.pack(fill="x")
        self._hint(f, t("history.hint"))
        frame, self.events = self._table(f, [
            ("time", "col.time", 110, "w"), ("event", "col.event", 130, "w"), ("agent", "col.agent", 170, "w"),
            ("task", "col.task", 280, "w"), ("change", "col.change", 250, "w"), ("reason", "col.reason", 200, "w")])
        frame.pack(fill="both", expand=True)

    # ---------- data ----------
    def _loop(self):
        s = self.scanner
        if s.version != self.seen_version:
            self.seen_version = s.version
            self.refresh()
        else:
            self._fill_live()
        if not self.chain.get("ok"):
            self.status.configure(text=self._chain_text(), fg=COLOR["bad"])
        elif self.notice:
            self.status.configure(text=self.notice, fg=COLOR["good"])
        elif s.error:
            self.status.configure(text=t("status.error", e=s.error), fg=COLOR["bad"])
        elif s.last:
            self.status.configure(text=t("status.ok", time=f"{s.last:%H:%M:%S}", path=config.data_dir()),
                                  fg=COLOR["muted"])
        self.after(int(os.environ.get("AGENT_SCORECARD_REFRESH_MS", 1500)), self._loop)

    def refresh(self):
        self.rules = config.rules()
        self.chain = history.verify(self.con)
        self._fill_cards()
        self._fill_live()
        agents = [r[0] for r in self.con.execute("SELECT DISTINCT agent_type FROM tasks ORDER BY agent_type")]
        self.f_agent.configure(values=[t("filter.all")] + agents)
        self.f_agent.set(self.agent_filter or t("filter.all"))
        self.p_agent.configure(values=agents)
        if not self.profile_agent and agents:
            cards = metrics.agent_cards(self.con, self.rules)
            self.profile_agent = cards[0]["agent"] if cards else agents[0]
        self._fill_tasks()
        self._fill_groups()
        self._fill_agents()
        self._fill_profile()
        self._fill_summary()
        self._fill_routing()
        self._fill_history()

    def _fill_cards(self):
        now = metrics.success_metrics(self.con, days=7)
        before = metrics.success_metrics(self.con, days=7, offset=7)
        everything = metrics.success_metrics(self.con)
        # Fall back to all time when the last 7 days are empty
        src, period = (now, t("period.week")) if now["tasks"] else (everything, t("period.all"))

        def put(key, text, change=None, lower_is_better=False, extra="", neutral=False):
            value, delta = self.cards[key]
            value.configure(text=text)
            if change is None or not now["tasks"]:
                delta.configure(text=extra or period, fg=COLOR["muted"])
                return
            good = change < 0 if lower_is_better else change > 0
            arrow = "▲" if change > 0 else "▼" if change < 0 else "■"
            color = "muted" if neutral or not change else ("good" if good else "bad")
            delta.configure(text=t("card.vs_prev", arrow=arrow, pct=pct(abs(change))), fg=COLOR[color])

        def rel(a, b):
            return None if a is None or not b else (a - b) / b

        put("first_attempt", pct(src["first_attempt"]),
            None if src["first_attempt"] is None or before["first_attempt"] is None
            else src["first_attempt"] - before["first_attempt"])
        put("tokens", num(src["tokens_per_success"]), rel(src["tokens_per_success"], before["tokens_per_success"]), True)
        put("cost", money(src["cost_per_task"], 3), rel(src["cost_per_task"], before["cost_per_task"]), True,
            extra=t("card.api_equiv", period=period) + (t("card.unpriced", n=src["unpriced"]) if src["unpriced"] else ""))
        put("duration", duration(src["duration_success"]), rel(src["duration_success"], before["duration_success"]), True)
        put("problems", f"{src['errors']} · {src['repeated_errors']} · {src['redundant']}")
        put("tasks", str(now["tasks"]), rel(now["tasks"], before["tasks"]) if before["tasks"] else None,
            extra=t("card.totals", total=everything["tasks"], ok=everything["successes"]), neutral=True)

    def _fill_live(self):
        self.live.delete(*self.live.get_children())
        now = datetime.now(timezone.utc)
        rows = list(self.con.execute("SELECT * FROM tasks WHERE state='running' ORDER BY started_at DESC"))
        for r in rows:
            try:
                elapsed = (now - datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))).total_seconds()
            except (AttributeError, ValueError):
                elapsed = None
            self.live.insert("", "end", iid=r["agent_id"], tags=("accent",), values=(
                r["agent_type"], r["description"], r["project"] or "—", duration(elapsed), num(r["weighted_tokens"]),
                r["tool_calls"], r["tool_errors"], r["model"] or "—"))
        self.live_info.configure(text=t("live.count", n=len(rows)) if rows else t("live.none"))

    def _filters_changed(self, _event=None):
        a = self.f_agent.get()
        self.agent_filter = None if a in ("", t("filter.all")) else a
        o = self.f_outcome.get()
        self.outcome_filter = next((x for x in OUTCOMES if t("outcome." + x) == o), None)
        self._fill_tasks()

    def _fill_tasks(self):
        selected = self.tasks.selection()
        self.tasks.delete(*self.tasks.get_children())
        query, args = "SELECT * FROM tasks WHERE 1=1", []
        if self.agent_filter:
            query += " AND agent_type=?"
            args.append(self.agent_filter)
        if self.outcome_filter:
            query += " AND outcome=?"
            args.append(self.outcome_filter)
        for r in self.con.execute(query + " ORDER BY started_at DESC LIMIT 1000", args):
            score = "—" if r["score"] is None else f"{r['score']:.0f}/{r['measurable_max']:.0f}"
            self.tasks.insert("", "end", iid=r["agent_id"], tags=(OUTCOME_COLOR.get(r["outcome"], "text"),), values=(
                local(r["started_at"]), r["agent_type"], r["description"],
                outcome_label(r["outcome"]) + ("  ⚑" if r["flagged"] else ""),
                score, tier_label(r["tier"]), num(r["weighted_tokens"]), money(r["cost_usd"])))
        if selected and self.tasks.exists(selected[0]):
            self.tasks.selection_set(selected[0])
            self.tasks.see(selected[0])

    def _show_detail(self):
        selected = self.tasks.selection()
        if not selected:
            return
        r = self.con.execute("SELECT t.*, v.vote FROM tasks t LEFT JOIN votes v USING (agent_id) WHERE agent_id=?",
                             (selected[0],)).fetchone()
        if not r:
            return
        d = self.detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        d.insert("end", f"{r['agent_type']}\n", "title")
        d.insert("end", f"{r['description']}\n", "bold")
        cat = t("cat." + r["category"]) if r["category"] else "—"
        diff = t("diff." + r["difficulty"]) if r["difficulty"] else "—"
        d.insert("end", f"{r['project'] or '—'} · {r['model'] or '—'} · {cat} / {diff}"
                        f"{t('detail.task_key', k=r['task_key']) if r['task_key'] else ''}\n\n", "small")
        breakdown = json.loads(r["breakdown"] or "{}")
        d.insert("end", outcome_label(r["outcome"]), OUTCOME_COLOR.get(r["outcome"], "text"))
        if r["score"] is not None:
            d.insert("end", t("detail.points", n=num(r["score"])), "bold")
            d.insert("end", t("detail.measurable", n=num(r["measurable_max"])), "small")
        if r["tier"]:
            d.insert("end", "   " + tier_label(r["tier"]), r["tier"] if r["tier"] in COLOR else "muted")
        if r["vote"]:
            d.insert("end", t("detail.vote", v=t("outcome." + r["vote"])), "small")
        d.insert("end", f"\n{render(breakdown.get('reason'))}\n\n")
        for line in breakdown.get("lines", []):
            p, m = line["points"], line["max"]
            color = "muted" if not line["measured"] else ("bad" if p < 0 else "good" if p >= m else "text")
            label = f"{p:+.0f}" if p < 0 or m == 0 else f"{p:.0f}/{m}"
            d.insert("end", f"{label:>7}  ", color)
            d.insert("end", t("section." + line["section"]), "bold")
            d.insert("end", ("" if line["measured"] else t("detail.unmeasured")) + "\n", "small")
            d.insert("end", f"         {render(line['note'])}\n", "small")
        d.insert("end", f"\n{t('detail.tokens')}\n", "bold")
        d.insert("end", t("detail.token_line", i=num(r["input_tokens"]), o=num(r["output_tokens"]),
                          w=num((r["cache_write_5m"] or 0) + (r["cache_write_1h"] or 0)), r=num(r["cache_read"])) + "\n"
                 + t("detail.cost_line", wt=num(r["weighted_tokens"]),
                     c=t("detail.no_price") if r["cost_usd"] is None else money(r["cost_usd"], 4),
                     d=duration(r["duration_s"])) + "\n", "small")
        criteria = json.loads(r["criteria"] or "[]")
        if criteria:
            d.insert("end", f"\n{t('detail.criteria')}\n", "bold")
            for c in criteria:
                extra = t("crit." + c["note"]) if c["note"] else ""
                d.insert("end", f"  {'✓' if c['met'] else '✗'} {t('crit.' + c['kind'])}: {c['value']} {extra}\n",
                         "good" if c["met"] else "bad")
        d.insert("end", f"\n{t('detail.tools')}\n", "bold")
        usage = json.loads(r["tool_usage"] or "{}")
        d.insert("end", "  " + (" · ".join(f"{n} {c}/{e}" for n, (c, e) in usage.items()) or t("none")) + "\n", "small")
        d.insert("end", f"\n{t('detail.report')}\n", "bold")
        d.insert("end", (r["final_report"] or "—")[:2500] + "\n")
        d.configure(state="disabled")

    def _vote(self, vote):
        selected = self.tasks.selection()
        if not selected:
            return
        set_vote(self.con, selected[0], vote, self.rules)
        self.refresh()
        self._show_detail()

    def _export(self, fmt):
        path = filedialog.asksaveasfilename(defaultextension=f".{fmt}", initialfile=f"agent-scorecard.{fmt}",
                                            filetypes=[(fmt.upper(), f"*.{fmt}")])
        if not path:
            return
        n = export.export_csv(self.con, Path(path)) if fmt == "csv" else export.export_json(self.con, Path(path),
                                                                                             self.rules)
        self.notice = t("export.done", n=n, path=path)
        self.after(8000, lambda: setattr(self, "notice", None))

    def _fill_groups(self):
        self.groups.delete(*self.groups.get_children())
        for g in metrics.task_groups(self.con)[:1000]:
            cost = money(g["cost"]) if g["priced"] else t("cost.partial", cost=money(g["cost"]))
            self.groups.insert("", "end", tags=(OUTCOME_COLOR.get(g["outcome"], "text"),), values=(
                local(g["started"]), g["label"], t("match.exact" if g["exact"] else "match.approx"), g["attempts"],
                ", ".join(g["agents"]), outcome_label(g["first_outcome"]), outcome_label(g["outcome"]),
                num(g["tokens"]), cost))

    def _fill_agents(self):
        self.agents.delete(*self.agents.get_children())
        for c in metrics.agent_cards(self.con, self.rules):
            tiers = c["tiers"]
            self.agents.insert("", "end", iid=c["agent"], tags=("text" if c["final"] else "muted",), values=(
                c["agent"], t("level." + c["level"]), num(c["career"]), num(c["mean_score"], 1),
                pct(c["success_rate"]), c["tasks"], c["pending"], tiers["diamond"], tiers["gold"], tiers["silver"],
                tiers["bronze"], num(c["mean_tokens_success"]), money(c["cost"]), c["flagged"] or ""))

    def _open_profile(self, _event):
        selected = self.agents.selection()
        if selected:
            self._select_profile(selected[0])
            self.book.select(TAB_PROFILE)

    def _select_profile(self, agent):
        self.profile_agent = agent
        self._fill_profile()

    def _profile_tasks(self):
        if self.profile_agent:
            self.agent_filter, self.outcome_filter = self.profile_agent, None
            self.f_agent.set(self.profile_agent)
            self.f_outcome.set(t("filter.all"))
            self._fill_tasks()
            self.book.select(TAB_TASKS)

    def _fill_profile(self):
        box = self.p_text
        box.configure(state="normal")
        box.delete("1.0", "end")
        self.p_cats.delete(*self.p_cats.get_children())
        if not self.profile_agent:
            box.insert("end", t("profile.empty"), "muted")
            box.configure(state="disabled")
            return
        self.p_agent.set(self.profile_agent)
        p = metrics.agent_profile(self.con, self.profile_agent, self.rules)
        lv = p["level"]
        box.insert("end", f"{p['agent']}\n", "title")
        box.insert("end", t("profile.level", level=t("level." + lv["key"]), points=num(p["career"])) + "\n", "bold")
        box.insert("end", (t("profile.next", left=num(lv["next_floor"] - p["career"]), next=t("level." + lv["next_key"]))
                           if lv["next_key"] else t("profile.max")) + "\n", "small")
        box.insert("end", t("profile.levels_note") + "\n", "small")

        c = p["counts"]
        box.insert("end", f"\n{t('profile.tasks_h')}\n", "bold")
        box.insert("end", t("profile.outcome_line", success=c["success"], partial=c["partial"], failed=c["failed"],
                            pending=c["pending"], running=c["running"]) + "\n")
        box.insert("end", t("profile.rate", rate=pct(p["success_rate"]), n=p["final"]))
        box.insert("end", ("" if p["reliable"] else t("profile.thin")) + "\n", "warn")
        box.insert("end", t("profile.points", gained=num(p["gained"]), lost=num(p["lost"])) + "\n")

        box.insert("end", f"\n{t('profile.tokens_h')}\n", "bold")
        box.insert("end", t("profile.tokens_line", i=num(p["input"]), o=num(p["output"]), w=num(p["cache_write"]),
                            r=num(p["cache_read"])) + "\n", "small")
        box.insert("end", t("profile.tokens_line2", t=num(p["tokens"]), s=num(p["tokens_per_success"]),
                            c=money(p["cost"]), unpriced=t("profile.unpriced", n=p["unpriced"]) if p["unpriced"] else "",
                            d=duration(p["duration_success"])) + "\n", "small")

        box.insert("end", f"\n{t('profile.tools_h')}\n", "bold")
        box.insert("end", "  " + (" · ".join(f"{n} {calls}/{err}" for n, calls, err in p["tools"]) or t("none")) + "\n",
                   "small")
        box.insert("end", f"\n{t('profile.errors_h')}\n", "bold")
        box.insert("end", t("profile.errors_line", e=p["tool_errors"], r=p["repeated_errors"], w=p["redundant"]) + "\n",
                   "small")

        box.insert("end", f"\n{t('profile.failures_h')}\n", "bold")
        if not p["failures"]:
            box.insert("end", t("profile.no_failures") + "\n", "small")
        for r in p["failures"][:15]:
            reason = render(json.loads(r["breakdown"] or "{}").get("reason"))
            box.insert("end", f"  {local(r['started_at'])}  ", "small")
            box.insert("end", f"{outcome_label(r['outcome'])}", OUTCOME_COLOR[r["outcome"]])
            box.insert("end", f"  {r['description']}\n", "text")
            box.insert("end", f"      {reason}\n", "small")

        box.insert("end", f"\n{t('profile.levels_h')}\n", "bold")
        if not p["level_ups"]:
            box.insert("end", t("profile.no_levels") + "\n", "small")
        for e in p["level_ups"]:
            key = "profile.level_up" if e["up"] else "profile.level_down"
            box.insert("end", "  " + t(key, at=local(e["at"], "%d.%m.%Y"), level=t("level." + e["level"])) + "\n",
                       "good" if e["up"] else "bad")
        box.configure(state="disabled")

        for cat in p["categories"]:
            self.p_cats.insert("", "end", tags=("text" if cat["reliable"] else "muted",), values=(
                t("cat." + cat["category"]), t("diff." + cat["difficulty"]), cat["n"], pct(cat["success_rate"]),
                num(cat["mean_score"], 1), t("reliable.yes" if cat["reliable"] else "reliable.no")))
        self.p_weeks = p["weeks"]
        self._draw_trend()

    def _draw_trend(self):
        cv = self.p_chart
        cv.delete("all")
        weeks = self.p_weeks
        if not weeks:
            return
        w, h = max(cv.winfo_width(), 200), int(cv["height"])
        top, bottom, left = 18, h - 34, 8
        slot = (w - 2 * left) / len(weeks)
        cv.create_line(left, bottom, w - left, bottom, fill=COLOR["line"])
        for i, wk in enumerate(weeks):
            x0 = left + i * slot + slot * 0.2
            x1 = left + (i + 1) * slot - slot * 0.2
            cx = (x0 + x1) / 2
            if wk["mean_score"] is not None:
                y = bottom - (bottom - top) * wk["mean_score"] / 100
                cv.create_rectangle(x0, y, x1, bottom, fill=COLOR["accent"], outline="")
                cv.create_text(cx, y - 8, text=num(wk["mean_score"]), fill=COLOR["text"], font=(FONT, 9, "bold"))
                cv.create_text(cx, (y + bottom) / 2, text=str(wk["n"]), fill="#ffffff", font=(FONT, 8))
            else:
                cv.create_text(cx, bottom - 8, text="–", fill=COLOR["muted"], font=(FONT, 9))
            cv.create_text(cx, bottom + 12, text=wk["start"].strftime("%d.%m"), fill=COLOR["muted"], font=(FONT, 8))
            if wk["success_rate"] is not None:
                cv.create_text(cx, bottom + 26, text=pct(wk["success_rate"]), fill=COLOR["muted"], font=(FONT, 8))

    def _fill_summary(self):
        for tree, unit, count in ((self.daily, "day", 14), (self.weekly, "week", 8)):
            tree.delete(*tree.get_children())
            for s in metrics.period_summary(self.con, unit, count):
                label = s["start"].strftime("%d.%m.%Y") if unit == "day" else \
                    t("summary.week_of", d=s["start"].strftime("%d.%m"))
                tree.insert("", "end", tags=("text" if s["tasks"] else "muted",), values=(
                    label, s["tasks"], pct(s["success_rate"]), pct(s["first_attempt"]), num(s["tokens_per_success"]),
                    money(s["cost_per_task"], 3), duration(s["duration_success"]), pct(s["test_pass"]),
                    f"{s['errors']} · {s['repeated_errors']} · {s['redundant']}"))

    def _fill_routing(self):
        self.routing.delete(*self.routing.get_children())
        for r in metrics.routing(self.con, self.rules["routing"]["min_tasks"]):
            b, ru = r["best"], r["runner_up"]
            self.routing.insert("", "end", tags=("text" if b else "muted",), values=(
                t("cat." + r["category"]), t("diff." + r["difficulty"]), b["agent"] if b else t("routing.none"),
                num(b and b["mean_score"], 1), pct(b and b["success"]), num(b and b["mean_tokens"]),
                f"{ru['agent']} ({num(ru['mean_score'])})" if ru else "—",
                t("routing.data", total=r["total"], agents=r["agents"])))

    def _chain_text(self):
        c = self.chain
        if c.get("ok"):
            return t("history.ok", n=c["events"])
        if c["problem"] == "missing_tasks":
            return t("history.missing_tasks", n=c["missing_tasks"])
        return t("history." + c["problem"], seq=c["seq"])

    def _fill_history(self):
        self.chain_label.configure(text=self._chain_text(), fg=COLOR["good"] if self.chain.get("ok") else COLOR["bad"])
        self.events.delete(*self.events.get_children())
        names = {r["agent_id"]: r["description"] for r in self.con.execute("SELECT agent_id, description FROM tasks")}
        for e in history.events(self.con, limit=1000):
            if e["kind"] == "vote":
                change = t("event.vote_change", vote=outcome_label(e["vote"]) if e["vote"] else t("none"),
                           previous=outcome_label(e["previous"]) if e["previous"] else t("none"))
                reason, color = "", "accent"
            elif e["kind"] == "scored":
                change = f"{outcome_label(e['outcome'])} · {num(e['score'])} ({e['delta']:+.0f})"
                reason, color = t("reason." + e["reason"]), "text"
            else:
                change = f"{outcome_label(e['old_outcome'])} → {outcome_label(e['outcome'])} ({e['delta']:+.0f})"
                reason, color = t("reason." + e["reason"]), "warn"
            self.events.insert("", "end", tags=(color,), values=(
                local(e["at"]), t("event." + e["kind"]), e.get("agent_type", "—"), names.get(e["agent_id"], "—"),
                change, reason))


if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)  # keeps text sharp on high-DPI screens
    except Exception:
        pass
    app = Dashboard()
    # Automation hooks used to take the README screenshots
    if os.environ.get("AGENT_SCORECARD_LANG"):
        app.lang.set(i18n.LANGUAGES[os.environ["AGENT_SCORECARD_LANG"]])
        app._change_language(None)
    if os.environ.get("AGENT_SCORECARD_TAB"):
        app.after(800, lambda: app.book.select(int(os.environ["AGENT_SCORECARD_TAB"])))
    if os.environ.get("AGENT_SCORECARD_SELECT_FIRST"):
        def _select_first():
            rows = app.tasks.get_children()
            if rows:
                app.tasks.selection_set(rows[int(os.environ["AGENT_SCORECARD_SELECT_FIRST"])])
        app.after(2500, _select_first)
    if os.environ.get("AGENT_SCORECARD_CLOSE_AFTER_MS"):
        app.after(int(os.environ["AGENT_SCORECARD_CLOSE_AFTER_MS"]), app.destroy)
    app.mainloop()
