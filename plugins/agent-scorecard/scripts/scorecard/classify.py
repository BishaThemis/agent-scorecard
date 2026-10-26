"""Task category, difficulty and cost. Difficulty comes only from the task definition; the tokens or
tool calls an agent spends never change it (otherwise an inefficient agent could make its own task
look "hard" and be compared against a looser reference)."""
import re

from .transcript import lower

DIFFICULTIES = ("easy", "medium", "hard")
CATEGORY_ALIASES = {"test": "testing", "hata ayıklama": "debugging", "inceleme": "review", "araştırma": "research",
                    "dokümantasyon": "docs", "yeniden düzenleme": "refactor", "planlama": "planning",
                    "uygulama": "implementation"}


def _hits(text: str, words: list[str]) -> int:
    # Match at word starts: "fix" hits "fixes" but not "prefix"; keeps suffixed Turkish words working
    return sum(len(re.findall(r"(?<!\w)" + re.escape(lower(w)), text)) for w in words)


def category(description: str, prompt: str, marker: str | None, rules: dict) -> str:
    """The short description given by the orchestrator weighs three times as much as the prompt start."""
    marker = CATEGORY_ALIASES.get(marker, marker)
    if marker and marker in rules["categories"]:
        return marker
    title, body = lower(description or ""), lower(prompt[:800])
    scores = {name: 3 * _hits(title, words) + _hits(body, words) for name, words in rules["categories"].items()}
    best = max(scores.values(), default=0)
    return next(name for name, s in scores.items() if s == best) if best else "other"


def difficulty(prompt: str, criteria_count: int, marker: str | None, rules: dict) -> str:
    if marker in DIFFICULTIES:
        return marker
    d = rules["difficulty"]
    text = lower(prompt)
    if any(lower(w) in text for w in d["hard_words"]):
        return "hard"
    length = len(prompt) + 300 * criteria_count
    if length <= d["easy_max_chars"] or any(lower(w) in text for w in d["easy_words"]):
        return "easy"
    return "medium" if length <= d["medium_max_chars"] else "hard"


def cost(model: str | None, m: dict, rules: dict) -> float | None:
    """Returns None for models without a configured price; estimates are never shown as real data."""
    if not model or not m.get("tokens_measured"):
        return None
    prices = rules["pricing"]
    candidates = [name for name in prices if model.startswith(name)]
    if not candidates:
        return None
    p = prices[max(candidates, key=len)]
    return (m["input_tokens"] * p["input"] + m["output_tokens"] * p["output"] + m["cache_write_5m"] * p["cache_write_5m"]
            + m["cache_write_1h"] * p["cache_write_1h"] + m["cache_read"] * p["cache_read"]) / 1_000_000
