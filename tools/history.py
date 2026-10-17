"""Version history per model: <project>/.cad/models/<model>/history/<id>/{script.py, params.json, note.txt}.

A snapshot is taken on every publish (cadview.publish_kinematic) and before a restore; identical states are not stored twice and only
the newest KEEP are kept. The note is what the user had last asked for in the chat, so the history reads like a project log."""
import hashlib
import json
import re
import shutil
import time
from pathlib import Path

KEEP = 60
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _hist(root, model):
    if not ID_RE.match(model or ""):
        raise ValueError("bad model id")
    return Path(root) / ".cad" / "models" / model / "history"


def _last_request(root, model):
    try:
        lines = (Path(root) / ".cad" / "chat.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("role") == "user" and m.get("model") in (model, None):
            return str(m.get("text", ""))[:200]
    return ""


def _params(root, model):
    f = Path(root) / ".cad" / "models" / model / "params.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def snapshot(root, model, script_rel):
    """Store the script and params as they are now. Returns the snapshot id, or None if this state is already the newest one."""
    d = _hist(root, model)
    script = (Path(root) / script_rel).read_text(encoding="utf-8")
    params = _params(root, model)
    digest = hashlib.sha1((script + "\0" + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:8]
    existing = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
    if existing and existing[-1].endswith("-" + digest):
        return None
    sid = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}-{digest}"
    s = d / sid
    s.mkdir(parents=True)
    (s / "script.py").write_text(script, encoding="utf-8")
    (s / "params.json").write_text(json.dumps(params), encoding="utf-8")
    (s / "note.txt").write_text(_last_request(root, model), encoding="utf-8")
    for old in sorted(p.name for p in d.iterdir())[:-KEEP]:
        shutil.rmtree(d / old, ignore_errors=True)
    return sid


def list_history(root, model):
    d = _hist(root, model)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir(), reverse=True):
        try:
            note = (p / "note.txt").read_text(encoding="utf-8")
        except OSError:
            note = ""
        out.append({"id": p.name, "time": p.name[:15], "note": note})
    return out


def read(root, model, sid):
    s = _hist(root, model) / sid
    if not ID_RE.match(sid) or not s.is_dir():
        raise KeyError(sid)
    return {"script": (s / "script.py").read_text(encoding="utf-8"), "params": json.loads((s / "params.json").read_text(encoding="utf-8"))}


def restore(root, model, sid, script_rel):
    """Put a snapshot's script and params back (the current state is snapshotted first, so a restore can be undone)."""
    state = read(root, model, sid)
    try:
        snapshot(root, model, script_rel)
    except OSError:
        pass
    (Path(root) / script_rel).write_text(state["script"], encoding="utf-8")
    pf = Path(root) / ".cad" / "models" / model / "params.json"
    if state["params"]:
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(json.dumps(state["params"]), encoding="utf-8")
    else:
        pf.unlink(missing_ok=True)
