"""Agent Scorecard desktop dashboard (tkinter, no extra dependencies)."""
import json
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scorecard import config, db, i18n, metrics  # noqa: E402
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


def duration(seconds):
    if seconds is None:
        return "—"
    s = int(seconds)
    return t("dur.h", h=s // 3600, m=s % 3600 // 60) if s >= 3600 else t("dur.m", m=s // 60, s=s % 60)


def local(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%d.%m %H:%M")
    except (AttributeError, ValueError):
        return "—"


def tier_label(tier):
    if not tier:
        return "—"
    return f"{TIER_MARK[tier]} {t('tier.' + tier)}" if tier in TIER_MARK else t("tier." + tier)


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
        self.geometry("1320x800")
        self.minsize(980, 620)
        self.configure(bg=COLOR["bg"])
        self.con = db.connect()
        self.rules = config.rules()
        self.scanner = Scanner()
        self.seen_version = -1
        self.agent_filter = None          # None = all
        self.outcome_filter = None
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
        s.configure("TNotebook.Tab", padding=(16, 7), font=(FONT, 10), background=COLOR["line"])
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
        self._agents_tab()
        self._routing_tab()

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

    def _table(self, parent, columns):
        frame = ttk.Frame(parent, style="Card.TFrame")
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse")
        for name, title, width, anchor in columns:
            tree.heading(name, text=t(title))
            tree.column(name, width=width, anchor=anchor, stretch=name in ("task", "suggested"))
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        for name, color in COLOR.items():
            tree.tag_configure(name, foreground=color)
        return frame, tree

    def _live_tab(self):
        f = ttk.Frame(self.book, padding=10)
        self.book.add(f, text=f"  {t('tab.live')}  ")
        self.live_info = tk.Label(f, text="", font=(FONT, 10), bg=COLOR["bg"], fg=COLOR["muted"], anchor="w")
        self.live_info.pack(fill="x", pady=(0, 6))
        frame, self.live = self._table(f, [
            ("agent", "col.agent", 190, "w"), ("task", "col.task", 360, "w"), ("project", "col.project", 140, "w"),
            ("elapsed", "col.elapsed", 90, "e"), ("tokens", "col.weighted", 120, "e"),
            ("calls", "col.calls", 100, "e"), ("errors", "col.errors", 60, "e"), ("model", "col.model", 140, "w")])
        frame.pack(fill="both", expand=True)

    def _tasks_tab(self):
        f = ttk.Frame(self.book, padding=10)
        self.book.add(f, text=f"  {t('tab.tasks')}  ")
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
        self.detail = tk.Text(right, wrap="word", font=(FONT, 10), relief="flat", bg=COLOR["card"],
                              fg=COLOR["text"], padx=4, pady=8, height=10)
        self.detail.pack(fill="both", expand=True, pady=(8, 0))
        for name, color in COLOR.items():
            self.detail.tag_configure(name, foreground=color)
        self.detail.tag_configure("title", font=(FONT, 12, "bold"))
        self.detail.tag_configure("bold", font=(FONT, 10, "bold"))
        self.detail.tag_configure("small", font=(FONT, 9), foreground=COLOR["muted"])
        self.detail.configure(state="disabled")

    def _place_sash(self, pane):
        """Puts the table/detail divider at ~63% once the pane has its real width."""
        if not pane.winfo_exists():
            return
        if pane.winfo_width() < 300:
            self.after(150, lambda: self._place_sash(pane))
        else:
            pane.sashpos(0, int(pane.winfo_width() * 0.63))

    def _agents_tab(self):
        f = ttk.Frame(self.book, padding=10)
        self.book.add(f, text=f"  {t('tab.agents')}  ")
        tk.Label(f, text=t("agents.hint"), bg=COLOR["bg"], fg=COLOR["muted"], anchor="w").pack(fill="x", pady=(0, 6))
        frame, self.agents = self._table(f, [
            ("agent", "col.agent", 200, "w"), ("total", "col.total", 100, "e"), ("mean", "col.mean", 80, "e"),
            ("success", "col.success", 70, "e"), ("tasks", "col.ntasks", 60, "e"),
            ("pending", "col.pending", 140, "e"), ("diamond", "tier.diamond", 64, "e"), ("gold", "tier.gold", 60, "e"),
            ("silver", "tier.silver", 60, "e"), ("bronze", "tier.bronze", 60, "e"),
            ("tokens", "col.tok_success", 170, "e"), ("cost", "col.total_cost", 100, "e"),
            ("flagged", "col.flagged", 80, "e")])
        frame.pack(fill="both", expand=True)
        self.agents.bind("<Double-1>", self._open_agent)

    def _routing_tab(self):
        f = ttk.Frame(self.book, padding=10)
        self.book.add(f, text=f"  {t('tab.routing')}  ")
        tk.Label(f, text=t("routing.hint", n=self.rules["routing"]["min_tasks"]), bg=COLOR["bg"], fg=COLOR["muted"],
                 anchor="w", justify="left", wraplength=1200).pack(fill="x", pady=(0, 6))
        frame, self.routing = self._table(f, [
            ("category", "col.category", 150, "w"), ("difficulty", "col.difficulty", 80, "w"),
            ("suggested", "col.suggested", 220, "w"), ("score", "col.mean", 80, "e"),
            ("success", "col.success", 70, "e"), ("tokens", "col.mean_tokens", 110, "e"),
            ("runner", "col.runner_up", 200, "w"), ("data", "col.data", 140, "w")])
        frame.pack(fill="both", expand=True)

    # ---------- data ----------
    def _loop(self):
        s = self.scanner
        if s.version != self.seen_version:
            self.seen_version = s.version
            self.refresh()
        else:
            self._fill_live()
        if s.error:
            self.status.configure(text=t("status.error", e=s.error), fg=COLOR["bad"])
        elif s.last:
            self.status.configure(text=t("status.ok", time=f"{s.last:%H:%M:%S}", path=config.data_dir()),
                                  fg=COLOR["muted"])
        self.after(int(os.environ.get("AGENT_SCORECARD_REFRESH_MS", 1500)), self._loop)

    def refresh(self):
        self.rules = config.rules()
        self._fill_cards()
        self._fill_live()
        agents = [r[0] for r in self.con.execute("SELECT DISTINCT agent_type FROM tasks ORDER BY agent_type")]
        self.f_agent.configure(values=[t("filter.all")] + agents)
        self.f_agent.set(self.agent_filter or t("filter.all"))
        self._fill_tasks()
        self._fill_agents()
        self._fill_routing()

    def _fill_cards(self):
        now = metrics.success_metrics(self.con, days=7)
        before = metrics.success_metrics(self.con, days=7, offset=7)
        everything = metrics.success_metrics(self.con)
        # Fall back to all time when the last 7 days are empty
        src, period = (now, t("period.week")) if now["tasks"] else (everything, t("period.all"))

        def put(key, text, change=None, lower_is_better=False, extra=""):
            value, delta = self.cards[key]
            value.configure(text=text)
            if change is None or not now["tasks"]:
                delta.configure(text=extra or period, fg=COLOR["muted"])
                return
            good = change < 0 if lower_is_better else change > 0
            arrow = "▲" if change > 0 else "▼" if change < 0 else "■"
            delta.configure(text=t("card.vs_prev", arrow=arrow, pct=pct(abs(change))),
                            fg=COLOR["good"] if good else COLOR["bad"] if change else COLOR["muted"])

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
            extra=t("card.totals", total=everything["tasks"], ok=everything["successes"]))

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
            outcome = t("outcome." + r["outcome"]) if r["outcome"] else "—"
            self.tasks.insert("", "end", iid=r["agent_id"], tags=(OUTCOME_COLOR.get(r["outcome"], "text"),), values=(
                local(r["started_at"]), r["agent_type"], r["description"], outcome + ("  ⚑" if r["flagged"] else ""),
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
        d.insert("end", t("outcome." + r["outcome"]) if r["outcome"] else "—", OUTCOME_COLOR.get(r["outcome"], "text"))
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

    def _fill_agents(self):
        self.agents.delete(*self.agents.get_children())
        for c in metrics.agent_cards(self.con):
            tiers = c["tiers"]
            self.agents.insert("", "end", iid=c["agent"], tags=("text" if c["success_rate"] is not None else "muted",),
                               values=(
                c["agent"], num(c["total_score"]), num(c["mean_score"], 1), pct(c["success_rate"]), c["tasks"],
                c["pending"], tiers["diamond"], tiers["gold"], tiers["silver"], tiers["bronze"],
                num(c["mean_tokens_success"]), money(c["cost"]), c["flagged"] or ""))

    def _open_agent(self, _event):
        selected = self.agents.selection()
        if selected:
            self.agent_filter, self.outcome_filter = selected[0], None
            self.f_agent.set(selected[0])
            self.f_outcome.set(t("filter.all"))
            self._fill_tasks()
            self.book.select(1)

    def _fill_routing(self):
        self.routing.delete(*self.routing.get_children())
        for r in metrics.routing(self.con, self.rules["routing"]["min_tasks"]):
            b, ru = r["best"], r["runner_up"]
            self.routing.insert("", "end", tags=("text" if b else "muted",), values=(
                t("cat." + r["category"]), t("diff." + r["difficulty"]), b["agent"] if b else t("routing.none"),
                num(b and b["mean_score"], 1), pct(b and b["success"]), num(b and b["mean_tokens"]),
                f"{ru['agent']} ({num(ru['mean_score'])})" if ru else "—",
                t("routing.data", total=r["total"], agents=r["agents"])))


if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)  # keeps text sharp on high-DPI screens
    except Exception:
        pass
    app = Dashboard()
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
