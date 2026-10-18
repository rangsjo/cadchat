"""Token usage of the assistant sessions that worked on a project, read from Claude Code transcripts (~/.claude/projects/*/*.jsonl).

A transcript counts when its text mentions the project's folder. Every assistant message carries its token usage; a message can be
written several times while it streams, so each message id is counted once (the largest values). Nothing leaves the machine."""
import json
import time
from pathlib import Path

KINDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
NAMES = ("input", "output", "cache_read", "cache_creation")
STATS = {"parsed": 0, "lines": 0}
_cache = {}                       # path -> {"size", "needle", "offset", "mentions", "rows"}: transcripts only grow, so each is read once, then only its new lines


def default_root():
    return Path.home() / ".claude" / "projects"


def _read_more(path, needle, state):
    """Continue reading a transcript from where the last read stopped (only complete lines), updating state in place:
    {"offset", "mentions", "rows": {message id: (timestamp, model, {kind: n})}}."""
    try:
        with open(path, "rb") as f:
            f.seek(state["offset"])
            data = f.read()
    except OSError:
        return state
    end = data.rfind(b"\n") + 1
    state["offset"] += end
    for raw in data[:end].splitlines():
        STATS["lines"] += 1
        line = raw.decode("utf-8", "replace")
        if not state["mentions"] and needle in line:
            state["mentions"] = True
        if '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message") or {}
        u = m.get("usage")
        if d.get("type") != "assistant" or not isinstance(u, dict) or not m.get("id"):
            continue
        cur = state["rows"].get(m["id"])
        vals = {k: int(u.get(k) or 0) for k in KINDS}
        if cur:
            vals = {k: max(vals[k], cur[2][k]) for k in KINDS}
        state["rows"][m["id"]] = (d.get("timestamp") or "", m.get("model") or "unknown", vals)
    return state


def _blank():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "messages": 0}


def _add(acc, vals):
    for k, n in zip(NAMES, KINDS):
        acc[k] += vals[n]
    acc["messages"] += 1


def collect(project, claude_dir=None, dirs=None):
    """Totals, per day, per model and per session for the sessions of this project."""
    needle = str(Path(project).resolve())
    files = []
    if dirs:
        for d in dirs:
            files += sorted(Path(d).expanduser().glob("*.jsonl"))
    else:
        base = Path(claude_dir) if claude_dir is not None else default_root()
        files = sorted(base.glob("*/*.jsonl")) if base.is_dir() else []
    total, days, models, sessions = _blank(), {}, {}, []
    used = 0
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        state = _cache.get(f)
        if not state or state["needle"] != needle or st.st_size < state["size"]:        # new, another project, or rewritten shorter: from the start
            state = {"needle": needle, "offset": 0, "mentions": False, "rows": {}, "size": 0}
            _cache[f] = state
            STATS["parsed"] += 1
        if st.st_size != state["size"]:
            _read_more(f, needle, state)
            state["size"] = st.st_size
        rows = state["rows"] if state["mentions"] else None
        if not rows:
            continue
        used += 1
        s = {"id": f.stem, **_blank(), "first": None, "last": None}
        for ts, model, vals in rows.values():
            for acc in (total, s, models.setdefault(model, _blank()), days.setdefault(ts[:10], {"date": ts[:10], **_blank()})):
                _add(acc, vals)
            s["first"] = min(s["first"] or ts, ts)
            s["last"] = max(s["last"] or ts, ts)
        sessions.append(s)
    today = {k: v for k, v in days.get(time.strftime("%Y-%m-%d", time.gmtime()), _blank()).items() if k != "date"}      # days are UTC dates
    inputs = total["input"] + total["cache_read"] + total["cache_creation"]
    return {"total": total, "today": today, "days": [days[k] for k in sorted(days) if k], "models": models,
            "sessions": sorted(sessions, key=lambda s: s["last"] or "", reverse=True), "sources": used,
            "cache_share": (total["cache_read"] / inputs) if inputs else 0.0, "updated": time.time()}
