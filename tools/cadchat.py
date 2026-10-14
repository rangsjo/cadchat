"""cadchat command line.

  ./cadchat new part NAME          create parts/NAME.py from templates/part.py
  ./cadchat new mechanism NAME     create parts/NAME.py from templates/mechanism.py (joints, presets, collision check)
  ./cadchat run NAME               run parts/NAME.py (builds and publishes the model)
  ./cadchat serve [--port N]       start the viewer
  ./cadchat list                   scripts in parts/ and whether they are built
  ./cadchat import FILE [--name N] import a STEP/STL file (e.g. from Creo) as a model to view, measure and lay out
  ./cadchat watch DIR              import every STEP/STL that appears or changes in DIR (a Creo export folder)
  ./cadchat export NAME [--out F]  a published model as one binary STL (reference pose)
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
WATCH_EXT = {".step", ".stp", ".stl"}


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
    target.write_text((HERE.parent / "templates" / KINDS[kind]).read_text(encoding="utf-8").replace("NAME", name), encoding="utf-8")
    return target


def list_scripts(root):
    root = Path(root)
    out = []
    for f in sorted((root / "parts").glob("*.py")):
        if f.stem.startswith("_"):
            continue
        out.append((f.stem, (root / ".cad" / "models" / f.stem / "model.json").exists()))
    return out


def scan_once(directory, state):
    """Files that appeared or changed and have stopped changing since the previous scan (so half-written exports are skipped)."""
    ready = []
    for f in sorted(Path(directory).iterdir()):
        if f.suffix.lower() not in WATCH_EXT or not f.is_file():
            continue
        st = f.stat()
        sig = (st.st_mtime_ns, st.st_size)
        known = state.get(f)
        if known is None or known["sig"] != sig:
            state[f] = {"sig": sig, "imported": False}
        elif not known["imported"]:
            known["imported"] = True
            ready.append(f)
    return ready


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
    i = sub.add_parser("import")
    i.add_argument("file")
    i.add_argument("--name")
    w = sub.add_parser("watch")
    w.add_argument("dir")
    w.add_argument("--interval", type=float, default=2.0)
    x = sub.add_parser("export")
    x.add_argument("name")
    x.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "new":
            print(f"created {create(a.kind, a.name, root)}")
        elif a.cmd == "list":
            for name, built in list_scripts(root):
                print(f"{name:24s} {'built' if built else 'not built'}")
        elif a.cmd in ("import", "watch", "export"):
            os.environ["CADCHAT_ROOT"] = str(root)
            sys.path.insert(0, str(HERE))
            import exchange
            if a.cmd == "import":
                if not Path(a.file).is_file():
                    raise ValueError(f"no such file: {a.file}")
                print(f"imported as model '{exchange.import_to_model(a.file, a.name)}'")
            elif a.cmd == "export":
                print(f"wrote {exchange.model_to_stl(a.name, a.out or f'exports/{a.name}.stl')}")
            else:
                import time
                state = {}
                print(f"watching {a.dir} for STEP/STL files (Ctrl-C to stop)")
                try:
                    while True:
                        for f in scan_once(a.dir, state):
                            try:
                                print(f"imported {f.name} as '{exchange.import_to_model(f)}'", flush=True)
                            except Exception as e:                    # a bad file must not stop the watcher
                                print(f"could not import {f.name}: {e}", flush=True)
                        time.sleep(a.interval)
                except KeyboardInterrupt:
                    pass
        elif a.cmd == "run":
            return subprocess.call([sys.executable, str(root / "parts" / f"{a.name}.py")], cwd=root,
                                   env={**os.environ, "CADCHAT_ROOT": str(root)})
        elif a.cmd == "serve":
            return subprocess.call([sys.executable, str(HERE / "cadserver.py"), "--port", str(a.port), "--root", str(root)])
    except (ValueError, FileExistsError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
