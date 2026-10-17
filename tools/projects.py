"""Projects, the registry of known projects and the library of reusable models.

A project is a folder with cadproject.json: its parts/ (model scripts), exports/ and .cad/ (published models, chat history, params).
The app itself (tools/, viewer, templates/, library/, examples/) holds no project data. Known projects are remembered in
<CADCHAT_HOME or ~/.config/cadchat>/projects.json so `cadchat projects` and "continue where I left off" work from any folder.
"""
import json
import os
import re
import socket
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
APP = TOOLS.parent
LIBRARY = APP / "library" / "parts"
EXAMPLES = APP / "examples"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
HACK = 'Path(__file__).resolve().parents[2] / "tools"'                    # how bundled scripts find the tools


def home():
    return Path(os.environ.get("CADCHAT_HOME") or Path.home() / ".config" / "cadchat")


def is_project(path):
    return (Path(path) / "cadproject.json").is_file()


def project_name(path):
    try:
        return json.loads((Path(path) / "cadproject.json").read_text(encoding="utf-8")).get("name") or Path(path).name
    except (OSError, ValueError):
        return Path(path).name


def _registry():
    try:
        return json.loads((home() / "projects.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(reg):
    home().mkdir(parents=True, exist_ok=True)
    (home() / "projects.json").write_text(json.dumps(reg, indent=1), encoding="utf-8")


def touch(path):
    """Remember a project as the most recently used."""
    path = str(Path(path).resolve())
    reg = [r for r in _registry() if r["path"] != path]
    reg.append({"path": path, "name": project_name(path), "last_used": time.time()})
    _save(reg)


def known_projects():
    """Most recently used first; folders that are gone or no longer projects are dropped."""
    reg = [r for r in _registry() if is_project(r["path"])]
    return sorted(({**r, "name": project_name(r["path"])} for r in reg), key=lambda r: -r["last_used"])


def init_project(path, name=None):
    path = Path(path).resolve()
    if is_project(path):
        raise FileExistsError(f"{path} is already a cadchat project")
    for d in ("parts", "exports", ".cad"):
        (path / d).mkdir(parents=True, exist_ok=True)
    (path / "cadproject.json").write_text(json.dumps({"name": name or path.name, "created": time.strftime("%Y-%m-%d")}, indent=1), encoding="utf-8")
    gi = path / ".gitignore"
    if not gi.exists():
        gi.write_text(".cad/\nexports/\n__pycache__/\n", encoding="utf-8")
    touch(path)
    return path


def _containing_project(path):
    p = Path(path).resolve()
    for q in (p, *p.parents):
        if is_project(q):
            return q
    return None


def resolve_project(arg=None, env=None, cwd=None):
    """--project, then CADCHAT_ROOT, then the project around the cwd, then the last used one, then the bundled examples."""
    env = os.environ if env is None else env
    for given in (arg, env.get("CADCHAT_ROOT")):
        if given:
            p = Path(given).resolve()
            if not is_project(p):
                raise ValueError(f"{p} is not a cadchat project (create one with: cadchat init {given})")
            return p
    found = _containing_project(cwd or Path.cwd())
    if found:
        return found
    known = known_projects()
    return Path(known[0]["path"]) if known else EXAMPLES


# ---- library of reusable models --------------------------------------------------------------------------------------
def library_list():
    return sorted(f.stem for f in LIBRARY.glob("*.py") if not f.stem.startswith("_"))


def retarget_script(text, old_name, new_name):
    """A library or template script made runnable from any project: absolute tools path, own name in the published paths."""
    for hack in (HACK, 'Path(__file__).resolve().parent.parent / "tools"'):
        text = text.replace(hack, f'os.environ.get("CADCHAT_TOOLS") or r"{TOOLS}"')
    if "import os" not in text and "CADCHAT_TOOLS" in text:
        text = text.replace("import sys", "import os\nimport sys", 1)
    return text.replace(f"parts/{old_name}.py", f"parts/{new_name}.py").replace(f"exports/{old_name}", f"exports/{new_name}")


def add_from_library(name, project, as_name=None):
    src = LIBRARY / f"{name}.py"
    if name not in library_list():
        raise ValueError(f"no library model '{name}' (have: {', '.join(library_list())})")
    new = as_name or name
    if not NAME_RE.match(new):
        raise ValueError("name must be letters, digits, _ or - (no spaces or slashes, not starting with _)")
    target = Path(project) / "parts" / f"{new}.py"
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    target.parent.mkdir(exist_ok=True)
    target.write_text(retarget_script(src.read_text(encoding="utf-8"), name, new), encoding="utf-8")
    return target


def pick_port(start=8765, span=40):
    for p in range(start, start + span):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError(f"no free port in {start}..{start + span - 1}")
