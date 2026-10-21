"""Optional features that live in the same code base but only show up when wanted.

A plugin has a backend part (tools/<name>_api.py, routes in cadserver) and a viewer part (tools/static/plugins/<name>.js, which adds its own tab).
It is enabled in Settings ("plugins": "creo") or by itself while its helper process is running (the Creo link writes .cad/creo/state.json)."""
import json
import time
from pathlib import Path

import settings

KNOWN = {"creo": "Creo Parametric link (Windows, experimental)"}


def available():
    return [{"id": k, "label": v} for k, v in KNOWN.items()]


def _running(root, name):
    """True while the plugin's helper keeps its state file fresh."""
    if name == "creo":
        try:
            st = json.loads((Path(root) / ".cad" / "creo" / "state.json").read_text(encoding="utf-8"))
            return time.time() - float(st.get("updated", 0)) < 15
        except (OSError, ValueError):
            return False
    return False


def enabled(root):
    chosen = [n.strip() for n in settings.load()["plugins"].split(",") if n.strip() in KNOWN]
    return [n for n in KNOWN if n in chosen or _running(root, n)]
