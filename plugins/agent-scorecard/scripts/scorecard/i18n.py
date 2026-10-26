"""User-facing text in English and Turkish. Scores store translation keys, not sentences,
so stored breakdowns follow the current language."""
from . import config

LANGUAGES = {"en": "English", "tr": "Türkçe"}

STRINGS = {
    "en": {
        # outcomes, tiers, categories, difficulty
        "outcome.success": "Success", "outcome.partial": "Partial", "outcome.failed": "Failed",
        "outcome.pending": "Awaiting verification", "outcome.running": "Running",
        "tier.diamond": "Diamond", "tier.gold": "Gold", "tier.silver": "Silver", "tier.bronze": "Bronze",
        "tier.none": "No reward",
        "cat.testing": "testing", "cat.debugging": "debugging", "cat.review": "review", "cat.research": "research",
        "cat.docs": "docs", "cat.refactor": "refactor", "cat.planning": "planning",
        "cat.implementation": "implementation", "cat.other": "other",
        "diff.easy": "easy", "diff.medium": "medium", "diff.hard": "hard",

        # score sections
        "section.success": "Task success", "section.false_claim": "False success claim",
        "section.tests": "Quality: tests", "section.requirements": "Quality: requirements",
        "section.no_regression": "Quality: no new errors", "section.tokens": "Token efficiency",
        "section.tools": "Tool efficiency", "section.errors": "Error handling", "section.reliability": "Reliability",

        # outcome reasons
        "reason.running": "The agent is still running.",
        "reason.unfinished": "The agent stopped before finishing.",
        "reason.no_report": "The agent did not deliver a final report (stop reason: {stop}).",
        "reason.user_vote": "Verified by the user.",
        "reason.partial_admitted": "The agent reported that part of the work is unfinished; {items}.",
        "reason.failed": "{items}.",
        "reason.partial_verified": "Checks passed, but the agent reported it could not do part of the work.",
        "reason.verified": "Tests, checks and acceptance criteria passed.",
        "reason.pending": "No tests, checks or acceptance criteria; waiting for user verification.",
        "fail.tests": "the last test run failed",
        "fail.checks": "the last build/lint check failed",
        "fail.criterion": "acceptance criterion not met: {value}",

        # line notes
        "note.false_claim": "The agent reported the work as done, but the evidence says otherwise.",
        "note.no_tests": "No tests were run; no points awarded.",
        "note.tests_passed": "{n} test runs, the last one passed.",
        "note.tests_failed": "{n} test runs, the last one failed.",
        "note.criteria": "{met}/{total} acceptance criteria met.",
        "note.user_verified": "Verified by the user.",
        "note.no_criteria": "No acceptance criteria defined (ACCEPT-FILE / ACCEPT-CMD); no points awarded.",
        "note.no_checks": "No tests or build/lint checks; no points awarded.",
        "note.checks_clean": "The final checks are clean.",
        "note.checks_dirty": "The final checks contain errors or a regression.",
        "note.gate_tokens": "Token points require verified success.",
        "note.gate_tools": "Tool efficiency points require verified success.",
        "note.tokens_unmeasured": "Token usage could not be measured.",
        "note.no_reference": "Not enough reference data: {n} successful tasks with the same category and "
                             "difficulty, at least {min} needed.",
        "note.tokens_ratio": "{tokens} weighted tokens; reference {ref} ({n} similar tasks), ratio {ratio}.",
        "note.tools": "{calls} calls; {waste} redundant repeats (same input, same output, nothing changed in between).",
        "note.unfinished_errors": "No points because the task did not finish.",
        "note.errors": "{errors} tool errors; the same error was repeated {repeats} times without changes.",
        "note.reliability_dedup": "The false-claim penalty was applied under task success; no second penalty here.",
        "note.unsupported_claim": "Claimed done or tests passing without any verification evidence.",
        "note.evidence": "The result is backed by verifiable evidence.",
        "note.disclosed": "The agent stated clearly that it did not verify the result.",
        "note.nothing": "No evidence and no claim.",

        # dashboard
        "app.title": "Agent Scorecard",
        "app.subtitle": "subagent performance · rule-based scoring · no extra LLM cost",
        "lang.label": "Language",
        "card.first_attempt": "First-attempt success", "card.tokens": "Tokens per successful task",
        "card.cost": "Cost per task", "card.duration": "Avg. completion time",
        "card.problems": "Errors · repeats · redundant", "card.tasks": "Tasks (last 7 days)",
        "period.week": "last 7 days", "period.all": "all time",
        "card.vs_prev": "{arrow} {pct} vs previous 7 days",
        "card.api_equiv": "{period} · API equivalent", "card.unpriced": " · {n} tasks without a price",
        "card.totals": "{total} total · {ok} successful",
        "tab.live": "Live", "tab.tasks": "Tasks", "tab.agents": "Agents & rewards", "tab.routing": "Routing",
        "col.agent": "Agent", "col.task": "Task", "col.project": "Project", "col.elapsed": "Elapsed",
        "col.weighted": "Weighted tokens", "col.calls": "Tool calls", "col.errors": "Errors", "col.model": "Model",
        "col.started": "Started", "col.outcome": "Outcome", "col.score": "Score", "col.reward": "Reward",
        "col.tokens": "Tokens", "col.cost": "Cost", "col.total": "Total score", "col.mean": "Avg. score",
        "col.success": "Success", "col.ntasks": "Tasks", "col.pending": "Awaiting verification",
        "col.tok_success": "Avg. tokens (successful)", "col.total_cost": "Total cost", "col.flagged": "Flagged",
        "col.category": "Category", "col.difficulty": "Difficulty", "col.suggested": "Suggested agent",
        "col.mean_tokens": "Avg. tokens", "col.runner_up": "Runner-up", "col.data": "Data",
        "live.count": "Subagents running now: {n}",
        "live.none": "No subagents are running. New ones appear here as soon as they start.",
        "filter.agent": "Agent:", "filter.outcome": "Outcome:", "filter.all": "All",
        "verify.label": "Verify:", "verify.success": "✓ Success", "verify.partial": "◐ Partial",
        "verify.failed": "✗ Failed", "verify.clear": "Clear vote",
        "agents.hint": "Double-click an agent to open its task history.",
        "routing.hint": "The highest average-scoring agent for each category and difficulty. A suggestion needs at "
                        "least {n} finished tasks per agent; below that, nothing is guessed.",
        "routing.none": "not enough data", "routing.data": "{total} tasks · agents: {agents}",
        "status.first": "First scan in progress…", "status.error": "Scan error: {e}",
        "status.ok": "Last scan {time} · data: {path}",
        "detail.points": "   {n} points", "detail.measurable": " / measurable {n}", "detail.vote": "   (user vote: {v})",
        "detail.unmeasured": "  (not measured)", "detail.task_key": " · task id {k}",
        "detail.tokens": "Tokens",
        "detail.token_line": "input {i} · output {o} · cache write {w} · cache read {r}",
        "detail.cost_line": "weighted {wt} · cost {c} · duration {d}", "detail.no_price": "no price configured",
        "detail.criteria": "Acceptance criteria", "detail.tools": "Tool usage (calls / errors)",
        "detail.report": "Agent's final report",
        "crit.file": "file", "crit.command": "command", "crit.missing": "missing",
        "crit.not_written_by_agent": "exists, but this agent did not create or change it", "crit.not_run": "never run",
        "none": "none", "dur.h": "{h} h {m} min", "dur.m": "{m} min {s} s",

        # CLI and hook
        "cli.title": "# Agent Scorecard",
        "cli.summary": "Tasks: {tasks} · successful: {ok} · first-attempt success: {first}",
        "cli.tokens": "Weighted tokens per successful task: {tok} · cost per task (API equivalent): {cost}",
        "cli.problems": "Tool errors: {e} · repeated errors: {r} · redundant calls: {w}",
        "cli.header": "| Agent | Tasks | Success | Avg. score | Total score | Diamond/Gold/Silver/Bronze | Pending |",
        "cli.routing": "Routing suggestions:",
        "cli.routing_line": "- {cat} / {diff}: {agent} (avg. {score}, {n} tasks)",
        "cli.scanned": "{n} transcripts updated.", "cli.rescored": "All tasks rescored.",
        "cli.opened": "Agent Scorecard dashboard opened.",
        "hint.header": "Agent Scorecard track record (consider it when routing tasks):",
        "hint.line": "- {cat} ({diff}): {agent} (avg. {score} points, {rate} success, {n} tasks)",
    },
    "tr": {
        "outcome.success": "Başarılı", "outcome.partial": "Kısmen", "outcome.failed": "Başarısız",
        "outcome.pending": "Doğrulama bekliyor", "outcome.running": "Çalışıyor",
        "tier.diamond": "Elmas", "tier.gold": "Altın", "tier.silver": "Gümüş", "tier.bronze": "Bronz",
        "tier.none": "Ödül yok",
        "cat.testing": "test", "cat.debugging": "hata ayıklama", "cat.review": "inceleme", "cat.research": "araştırma",
        "cat.docs": "dokümantasyon", "cat.refactor": "yeniden düzenleme", "cat.planning": "planlama",
        "cat.implementation": "uygulama", "cat.other": "diğer",
        "diff.easy": "kolay", "diff.medium": "orta", "diff.hard": "zor",

        "section.success": "Görev başarısı", "section.false_claim": "Yanlış başarı bildirimi",
        "section.tests": "Kalite: testler", "section.requirements": "Kalite: gereksinimler",
        "section.no_regression": "Kalite: yeni hata yok", "section.tokens": "Token verimliliği",
        "section.tools": "Araç verimliliği", "section.errors": "Hata yönetimi", "section.reliability": "Güvenilirlik",

        "reason.running": "Ajan hâlâ çalışıyor.",
        "reason.unfinished": "Ajan görevi bitirmeden durdu.",
        "reason.no_report": "Ajan son raporunu vermedi (durma nedeni: {stop}).",
        "reason.user_vote": "Kullanıcı doğrulaması.",
        "reason.partial_admitted": "Ajan işin eksik kaldığını bildirdi; {items}.",
        "reason.failed": "{items}.",
        "reason.partial_verified": "Doğrulamalar geçti ama ajan işin bir kısmını yapamadığını bildirdi.",
        "reason.verified": "Testler, kontroller ve kabul kriterleri geçti.",
        "reason.pending": "Test, kontrol veya kabul kriteri yok; sonuç kullanıcı onayı bekliyor.",
        "fail.tests": "son test çalıştırması başarısız",
        "fail.checks": "son build/lint kontrolü başarısız",
        "fail.criterion": "kabul kriteri karşılanmadı: {value}",

        "note.false_claim": "Ajan işi tamamladığını bildirdi ama kanıtlar aksini gösteriyor.",
        "note.no_tests": "Test çalıştırılmadı; puan verilmedi.",
        "note.tests_passed": "{n} test çalıştırması, sonuncusu geçti.",
        "note.tests_failed": "{n} test çalıştırması, sonuncusu kaldı.",
        "note.criteria": "{met}/{total} kabul kriteri karşılandı.",
        "note.user_verified": "Kullanıcı doğrulaması.",
        "note.no_criteria": "Kabul kriteri tanımlanmadı (ACCEPT-FILE / ACCEPT-CMD); puan verilmedi.",
        "note.no_checks": "Test veya build/lint kontrolü yok; puan verilmedi.",
        "note.checks_clean": "Son doğrulamalar temiz.",
        "note.checks_dirty": "Son doğrulamalarda hata veya gerileme var.",
        "note.gate_tokens": "Başarı doğrulanmadan token puanı verilmez.",
        "note.gate_tools": "Başarı doğrulanmadan araç verimliliği puanı verilmez.",
        "note.tokens_unmeasured": "Token tüketimi ölçülemedi.",
        "note.no_reference": "Yetersiz referans: aynı kategori ve zorlukta {n} başarılı görev var, en az {min} gerekli.",
        "note.tokens_ratio": "{tokens} ağırlıklı token; referans {ref} ({n} benzer görev), oran {ratio}.",
        "note.tools": "{calls} çağrı; {waste} gereksiz tekrar (aynı girdi, aynı çıktı, arada değişiklik yok).",
        "note.unfinished_errors": "Görev bitmediği için puan verilmedi.",
        "note.errors": "{errors} araç hatası; {repeats} kez aynı hata değişiklik yapmadan tekrarlandı.",
        "note.reliability_dedup": "Yanlış bildirim cezası başarı bölümünde uygulandı; burada tekrar ceza yok.",
        "note.unsupported_claim": "Hiçbir doğrulama kanıtı olmadan tamamlandı/testler geçti iddiası.",
        "note.evidence": "Sonuç doğrulanabilir kanıtlarla destekleniyor.",
        "note.disclosed": "Ajan doğrulama yapmadığını açıkça belirtti.",
        "note.nothing": "Kanıt yok, iddia da yok.",

        "app.title": "Agent Scorecard",
        "app.subtitle": "alt ajan performansı · kural tabanlı puanlama · ek LLM maliyeti yok",
        "lang.label": "Dil",
        "card.first_attempt": "İlk denemede başarı", "card.tokens": "Başarılı görev başına token",
        "card.cost": "Görev başına maliyet", "card.duration": "Ort. tamamlanma süresi",
        "card.problems": "Hata · tekrar · gereksiz", "card.tasks": "Görev (son 7 gün)",
        "period.week": "son 7 gün", "period.all": "tüm zamanlar",
        "card.vs_prev": "{arrow} {pct} önceki 7 güne göre",
        "card.api_equiv": "{period} · API eşdeğeri", "card.unpriced": " · {n} görevde fiyat yok",
        "card.totals": "{total} toplam · {ok} başarılı",
        "tab.live": "Canlı", "tab.tasks": "Görevler", "tab.agents": "Ajanlar ve ödüller", "tab.routing": "Yönlendirme",
        "col.agent": "Ajan", "col.task": "Görev", "col.project": "Proje", "col.elapsed": "Süre",
        "col.weighted": "Ağırlıklı token", "col.calls": "Araç çağrısı", "col.errors": "Hata", "col.model": "Model",
        "col.started": "Başlangıç", "col.outcome": "Sonuç", "col.score": "Puan", "col.reward": "Ödül",
        "col.tokens": "Token", "col.cost": "Maliyet", "col.total": "Toplam puan", "col.mean": "Ort. puan",
        "col.success": "Başarı", "col.ntasks": "Görev", "col.pending": "Doğrulama bekleyen",
        "col.tok_success": "Başarılı görev token ort.", "col.total_cost": "Toplam maliyet", "col.flagged": "İncelemede",
        "col.category": "Kategori", "col.difficulty": "Zorluk", "col.suggested": "Önerilen ajan",
        "col.mean_tokens": "Ort. token", "col.runner_up": "Alternatif", "col.data": "Veri",
        "live.count": "Şu anda çalışan alt ajan: {n}",
        "live.none": "Şu anda çalışan alt ajan yok. Yeni bir alt ajan başladığında burada görünür.",
        "filter.agent": "Ajan:", "filter.outcome": "Sonuç:", "filter.all": "Tümü",
        "verify.label": "Doğrula:", "verify.success": "✓ Başarılı", "verify.partial": "◐ Kısmen",
        "verify.failed": "✗ Başarısız", "verify.clear": "Oyu kaldır",
        "agents.hint": "Ajana çift tıklayınca geçmiş görevleri açılır.",
        "routing.hint": "Her kategori ve zorlukta en yüksek ortalama puanlı ajan. Öneri için ajan başına en az {n} "
                        "sonuçlanmış görev gerekir; altında tahmin yapılmaz.",
        "routing.none": "yetersiz veri", "routing.data": "{total} görev · {agents} ajan",
        "status.first": "İlk tarama yapılıyor…", "status.error": "Tarama hatası: {e}",
        "status.ok": "Son tarama {time} · veri: {path}",
        "detail.points": "   {n} puan", "detail.measurable": " / ölçülebilir {n}", "detail.vote": "   (kullanıcı oyu: {v})",
        "detail.unmeasured": "  (ölçülemedi)", "detail.task_key": " · görev kodu {k}",
        "detail.tokens": "Tokenlar",
        "detail.token_line": "girdi {i} · çıktı {o} · önbelleğe yazma {w} · önbellekten okuma {r}",
        "detail.cost_line": "ağırlıklı {wt} · maliyet {c} · süre {d}", "detail.no_price": "fiyatı bilinmiyor",
        "detail.criteria": "Kabul kriterleri", "detail.tools": "Araç kullanımı (çağrı / hata)",
        "detail.report": "Ajanın son raporu",
        "crit.file": "dosya", "crit.command": "komut", "crit.missing": "yok",
        "crit.not_written_by_agent": "dosya var ama bu ajan oluşturmadı/değiştirmedi", "crit.not_run": "çalıştırılmadı",
        "none": "yok", "dur.h": "{h} sa {m} dk", "dur.m": "{m} dk {s} sn",

        "cli.title": "# Agent Scorecard",
        "cli.summary": "Görev: {tasks} · başarılı: {ok} · ilk denemede başarı: {first}",
        "cli.tokens": "Başarılı görev başına ağırlıklı token: {tok} · görev başına maliyet (API eşdeğeri): {cost}",
        "cli.problems": "Araç hatası: {e} · tekrarlanan hata: {r} · gereksiz çağrı: {w}",
        "cli.header": "| Ajan | Görev | Başarı | Ort. puan | Toplam puan | Elmas/Altın/Gümüş/Bronz | Bekleyen |",
        "cli.routing": "Yönlendirme önerileri:",
        "cli.routing_line": "- {cat} / {diff}: {agent} (ort. {score}, {n} görev)",
        "cli.scanned": "{n} transkript güncellendi.", "cli.rescored": "Tüm görevler yeniden puanlandı.",
        "cli.opened": "Agent Scorecard paneli açıldı.",
        "hint.header": "Agent Scorecard geçmiş performansı (görev yönlendirirken dikkate al):",
        "hint.line": "- {cat} ({diff}): {agent} (ort. {score} puan, {rate} başarı, {n} görev)",
    },
}

_language = "en"


def set_language(code: str | None) -> None:
    global _language
    _language = code if code in STRINGS else "en"


def language() -> str:
    return _language


def load_language() -> str:
    set_language(config.settings().get("language", "en"))
    return _language


def num(value, decimals: int = 0, empty: str = "—") -> str:
    if value is None:
        return empty
    text = f"{value:,.{decimals}f}"
    if _language == "tr":
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text


def pct(ratio, empty: str = "—") -> str:
    if ratio is None:
        return empty
    n = num(ratio * 100)
    return f"%{n}" if _language == "tr" else f"{n}%"


def t(key: str, **params) -> str:
    text = STRINGS[_language].get(key) or STRINGS["en"].get(key) or key
    return text.format(**params) if params else text


def render(n: dict | None) -> str:
    """Renders a stored note {"key", "params"}; numbers are formatted for the current language."""
    if not n:
        return ""
    params = {}
    for k, v in (n.get("params") or {}).items():
        if k == "items":
            params[k] = "; ".join(render(i) for i in v)
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            params[k] = v
        else:
            params[k] = num(v, 0 if float(v).is_integer() else 2)
    text = t(n["key"], **params)
    return text[:1].upper() + text[1:]
