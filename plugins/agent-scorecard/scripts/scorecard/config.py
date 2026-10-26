"""Paths, rules and user settings."""
import hashlib
import json
import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def data_dir() -> Path:
    # Not under AppData: the Microsoft Store build of Python virtualizes AppData writes, so a hook
    # and a dashboard started by different Python installs would otherwise see different databases.
    path = Path(os.environ.get("AGENT_SCORECARD_DATA") or Path.home() / ".agent-scorecard")
    path.mkdir(parents=True, exist_ok=True)
    return path


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _merge(target: dict, source: dict) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def rules() -> dict:
    """Default rules, overridden by rules.json in the data directory if present."""
    with open(PACKAGE / "rules.json", encoding="utf-8") as f:
        result = json.load(f)
    override = data_dir() / "rules.json"
    if override.exists():
        with open(override, encoding="utf-8") as f:
            _merge(result, json.load(f))
    return result


def rules_hash(rules: dict) -> str:
    """Short fingerprint of the effective rules, stored with every score."""
    return hashlib.sha256(json.dumps(rules, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def remember_plugin_root(scripts_dir: Path) -> None:
    """Claude Code installs each plugin version in its own folder. The desktop shortcut starts a fixed
    launcher in the data directory, which reads this file to find the current version's dashboard."""
    target = data_dir() / "plugin_root.txt"
    value = str(Path(scripts_dir).resolve())
    try:
        if not target.exists() or target.read_text(encoding="utf-8").strip() != value:
            target.write_text(value, encoding="utf-8")
    except OSError:
        pass


def settings() -> dict:
    try:
        return json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_setting(key: str, value) -> None:
    current = settings()
    current[key] = value
    (data_dir() / "settings.json").write_text(json.dumps(current, indent=2), encoding="utf-8")
