"""Command line: python scorecard_cli.py [report|scan|rescore|dashboard] [--lang en|tr]
               python scorecard_cli.py export [--format json|csv] [--out FILE]"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from scorecard import config, db, export, i18n, metrics  # noqa: E402
from scorecard.i18n import num, pct, t  # noqa: E402
from scorecard.ingest import scan  # noqa: E402
from scorecard.scoring import rescore_all  # noqa: E402


def report(con, rules) -> str:
    s = metrics.success_metrics(con)
    lines = [
        t("cli.title"),
        t("cli.summary", tasks=s["tasks"], ok=s["successes"], first=pct(s["first_attempt"])),
        t("cli.tokens", tok=num(s["tokens_per_success"]),
          cost="—" if s["cost_per_task"] is None else "$" + num(s["cost_per_task"], 4)),
        t("cli.problems", e=s["errors"], r=s["repeated_errors"], w=s["redundant"]),
        "", t("cli.header"), "|---|---|---:|---:|---:|---:|---|---:|",
    ]
    for c in metrics.agent_cards(con, rules):
        tiers = "/".join(str(c["tiers"][x]) for x in metrics.TIERS)
        lines.append(f"| {c['agent']} | {t('level.' + c['level'])} | {num(c['career'])} | {c['tasks']} "
                     f"| {pct(c['success_rate'])} | {num(c['mean_score'], 1)} | {tiers} | {c['pending']} |")
    suggestions = [r for r in metrics.routing(con, rules["routing"]["min_tasks"]) if r["best"]]
    if suggestions:
        lines += ["", t("cli.routing")]
        lines += [t("cli.routing_line", cat=t(f"cat.{r['category']}"), diff=t(f"diff.{r['difficulty']}"),
                    agent=r["best"]["agent"], score=num(r["best"]["mean_score"]), n=r["best"]["n"])
                  for r in suggestions]
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    if "--lang" in argv:
        i = argv.index("--lang")
        i18n.set_language(argv[i + 1] if i + 1 < len(argv) else "en")
        del argv[i:i + 2]
    else:
        i18n.load_language()
    command = argv[0] if argv else "report"
    if command == "dashboard":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        subprocess.Popen([str(pythonw if pythonw.exists() else sys.executable), str(HERE / "dashboard.pyw")],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        print(t("cli.opened"))
        return
    rules = config.rules()
    con = db.connect()
    if command == "scan":
        print(t("cli.scanned", n=scan(con, rules)))
    elif command == "rescore":
        rescore_all(con, rules)
        print(t("cli.rescored"))
    elif command == "export":
        fmt = argv[argv.index("--format") + 1] if "--format" in argv else "json"
        out = Path(argv[argv.index("--out") + 1] if "--out" in argv else f"agent-scorecard-export.{fmt}").resolve()
        scan(con, rules)
        n = export.export_csv(con, out) if fmt == "csv" else export.export_json(con, out, rules)
        print(t("cli.exported", n=n, path=out))
    else:
        scan(con, rules)
        print(report(con, rules))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
