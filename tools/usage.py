"""Token usage of the assistant sessions that worked on a project, read from Claude Code transcripts (~/.claude/projects/*/*.jsonl).

A transcript counts when its text mentions the project's folder. Every assistant message carries its token usage; a message can be
written several times while it streams, so each message id is counted once (the largest values). Nothing leaves the machine."""
import json
import time
from pathlib import Path

KINDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
NAMES = ("input", "output", "cache_read", "cache_creation")
STATS = {"parsed": 0}
_cache = {}                       # path -> ((mtime_ns, size), parsed rows or None when the file does not mention the project, project)


def default_root():
    return Path.home() / ".claude" / "projects"


def _parse(path, needle):
    """{message id: (timestamp, model, {kind: n})} for one transcript, or None if it never mentions the project."""
    STATS["parsed"] += 1
    mentions, rows = False, {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not mentions and needle in line:
                    mentions = True
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
                cur = rows.get(m["id"])
                vals = {k: int(u.get(k) or 0) for k in KINDS}
                if cur:
                    vals = {k: max(vals[k], cur[2][k]) for k in KINDS}
                rows[m["id"]] = (d.get("timestamp") or "", m.get("model") or "unknown", vals)
    except OSError:
        return None
    return rows if mentions else None


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
        key = (st.st_mtime_ns, st.st_size)
        hit = _cache.get(f)
        if not hit or hit[0] != key or hit[2] != needle:
            hit = (key, _parse(f, needle), needle)
            _cache[f] = hit
        rows = hit[1]
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
