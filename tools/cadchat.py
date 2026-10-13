"""cadchat command line.

  ./cadchat new part NAME          create parts/NAME.py from templates/part.py
  ./cadchat new mechanism NAME     create parts/NAME.py from templates/mechanism.py (joints, presets, collision check)
  ./cadchat run NAME               run parts/NAME.py (builds and publishes the model)
  ./cadchat serve [--port N]       start the viewer
  ./cadchat list                   scripts in parts/ and whether they are built
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
KINDS = {"part": "part.py", "mechanism": "mechanism.py"}


def default_root():
    return Path(os.environ.get("CADCHAT_ROOT") or HERE.parent)


def create(kind, name, root):
    if kind not in KINDS:
        raise ValueError(f"unknown kind '{kind}' (use: {', '.join(KINDS)})")
    if not NAME_RE.match(name or ""):
        raise ValueError("name must be letters, digits, _ or - (no spaces or slashes, not starting with _)")
    target = Path(root) / "parts" / f"{name}.py"
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    target.parent.mkdir(exist_ok=True)
    target.write_text((HERE.parent / "templates" / KINDS[kind]).read_text().replace("NAME", name))
    return target


def list_scripts(root):
    root = Path(root)
    out = []
    for f in sorted((root / "parts").glob("*.py")):
        if f.stem.startswith("_"):
            continue
        out.append((f.stem, (root / ".cad" / "models" / f.stem / "model.json").exists()))
    return out


def main(argv=None, root=None):
    root = Path(root) if root else default_root()
    ap = argparse.ArgumentParser(prog="cadchat")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("kind")
    n.add_argument("name")
    r = sub.add_parser("run")
    r.add_argument("name")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8765)
    sub.add_parser("list")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "new":
            print(f"created {create(a.kind, a.name, root)}")
        elif a.cmd == "list":
            for name, built in list_scripts(root):
                print(f"{name:24s} {'built' if built else 'not built'}")
        elif a.cmd == "run":
            return subprocess.call([sys.executable, str(root / "parts" / f"{a.name}.py")], cwd=root,
                                   env={**os.environ, "CADCHAT_ROOT": str(root)})
        elif a.cmd == "serve":
            return subprocess.call([sys.executable, str(HERE / "cadserver.py"), "--port", str(a.port), "--root", str(root)])
    except (ValueError, FileExistsError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
