"""User settings, kept in <CADCHAT_HOME or ~/.config/cadchat>/settings.json (shared by all projects).

provider        which agent: claude, copilot, codex, gemini or custom (tools/providers.py); assistant_mode: session (interactive agent that listens) or message
                (the bridge runs the agent once per message); setup_done: the first-start wizard was completed;
assistant_cmd   the command of a custom agent (provider custom), terminal: how to open a terminal for it ("" = first one found),
projects_dir    where new projects are created, clearance: default glue gap for joints (mm), auto_open_chat: pop the chat open on a reply,
plugins         optional features to show, comma separated (creo), see tools/plugins.py;
usage_dirs      folders with Claude Code transcripts to read token usage from ("" = all of ~/.claude/projects that mention the project),
export_dir      where exports are written ("" = the project's exports folder).
Environment variables CADCHAT_ASSISTANT_CMD and CADCHAT_TERMINAL still override the file."""
import json
from pathlib import Path

import projects

DEFAULTS = {"provider": "claude", "assistant_mode": "session", "setup_done": False, "assistant_cmd": "claude", "terminal": "", "projects_dir": "~/cad-projects", "clearance": 0.2, "auto_open_chat": True, "export_dir": "", "usage_dirs": "", "plugins": ""}


def _file():
    return projects.home() / "settings.json"


def load():
    out = dict(DEFAULTS)
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
        for k in DEFAULTS:
            if k in raw and type(raw[k]) is type(DEFAULTS[k]) or (k == "clearance" and isinstance(raw.get(k), (int, float))):
                out[k] = raw[k]
    except (OSError, ValueError):
        pass
    return out


def _check(k, v):
    if k not in DEFAULTS:
        raise ValueError(f"unknown setting: {k}")
    if k == "clearance":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 2:
            raise ValueError("clearance must be a number between 0 and 2 mm")
        return float(v)
    if k in ("auto_open_chat", "setup_done"):
        if not isinstance(v, bool):
            raise ValueError(f"{k} must be true or false")
        return v
    if k == "plugins":
        import plugins
        names = [n.strip() for n in v.split(",") if n.strip()] if isinstance(v, str) else None
        if names is None or any(n not in plugins.KNOWN for n in names):
            raise ValueError("plugins: a comma separated list of: " + ", ".join(plugins.KNOWN))
        return ",".join(names)
    if k == "provider":
        import providers
        if v not in [p["id"] for p in providers.catalog()]:
            raise ValueError("provider must be one of: " + ", ".join(p["id"] for p in providers.catalog()))
        return v
    if k == "assistant_mode":
        if v not in ("session", "message"):
            raise ValueError("assistant_mode must be 'session' (live interactive agent) or 'message' (one run per chat message)")
        return v
    if not isinstance(v, str) or len(v) > 300:
        raise ValueError(f"{k} must be text")
    if k in ("assistant_cmd", "projects_dir") and not v.strip():
        raise ValueError(f"{k} must not be empty")
    return v.strip()


def save(changes):
    """Validate and store changes (all or nothing); returns the new settings."""
    new = {k: _check(k, v) for k, v in changes.items()}
    cur = load()
    cur.update(new)
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(cur, indent=1), encoding="utf-8")
    return cur


def projects_dir():
    return Path(load()["projects_dir"]).expanduser().resolve()
