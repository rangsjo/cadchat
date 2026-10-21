"""Backend of the Creo plugin: the link (tools/creolink.py) and the viewer share two files in <project>/.cad/creo/: state.json (written by the link)
and commands.jsonl (appended by the viewer through the server)."""
import json
import secrets
import time
from pathlib import Path


class BadCommand(ValueError):
    pass


def state(cad):
    f = Path(cad) / "creo" / "state.json"
    if not f.exists():
        return {"connected": False, "running": False}
    try:
        st = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return {"connected": False, "running": False}
    st["running"] = time.time() - float(st.get("updated", 0)) < 15      # the link rewrites the state every couple of seconds
    if not st["running"]:
        st["connected"] = False
    return st


def command(cad, d):
    cmd = d.get("cmd")
    if cmd not in ("sync", "set", "regenerate", "auto_sync"):
        raise BadCommand("unknown command")
    out = {"cmd": cmd, "id": secrets.token_hex(4)}
    if cmd == "set":
        name, value = d.get("name"), d.get("value")
        if not isinstance(name, str) or not 0 < len(name) <= 80 or not name.isprintable():
            raise BadCommand("bad parameter name")
        if isinstance(value, bool) or not isinstance(value, (int, float, str)) or (isinstance(value, str) and len(value) > 200):
            raise BadCommand("value must be a number or a short text")
        out.update(name=name, value=value)
    if cmd == "auto_sync":
        if not isinstance(d.get("value"), bool):
            raise BadCommand("auto_sync needs true or false")
        out["value"] = d["value"]
    (Path(cad) / "creo").mkdir(exist_ok=True)
    with open(Path(cad) / "creo" / "commands.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(out) + "\n")
    return {"ok": True, "id": out["id"]}
