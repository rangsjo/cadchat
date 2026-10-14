"""cadchat command line.

  ./cadchat new part NAME          create parts/NAME.py from templates/part.py
  ./cadchat new mechanism NAME     create parts/NAME.py from templates/mechanism.py (joints, presets, collision check)
  ./cadchat run NAME               run parts/NAME.py (builds and publishes the model)
  ./cadchat start [--port N]       start the viewer in the background (does nothing if it already runs)
  ./cadchat restart                restart it; open pages and the chat keep working
  ./cadchat stop | status          stop it / show where it runs
  ./cadchat serve [--port N]       run the viewer in this terminal (Ctrl-C stops it)
  ./cadchat list                   scripts in parts/ and whether they are built
  ./cadchat import FILE [--name N] import a STEP/STL file (e.g. from Creo) as a model to view, measure and lay out
  ./cadchat watch DIR              import every STEP/STL that appears or changes in DIR (a Creo export folder)
  ./cadchat export NAME [--out F]  a published model as one binary STL (reference pose)
"""
import argparse
import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
KINDS = {"part": "part.py", "mechanism": "mechanism.py"}
WATCH_EXT = {".step", ".stp", ".stl"}
SERVER = HERE / "cadserver.py"
DEFAULT_PORT = 8765


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


# ---- the viewer server: start / stop / restart / status ---------------------------------------------------------------------
def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), 0.3).close()
        return True
    except OSError:
        return False


def _is_cadchat(port):
    """True if what listens on the port is a cadchat server (not some other program)."""
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=1.5)
        c.request("GET", "/api/version", headers={"Host": f"127.0.0.1:{port}"})
        r = c.getresponse()
        return r.status == 200 and "models" in json.loads(r.read())
    except (OSError, ValueError):
        return False


def _info_file(root):
    return Path(root) / ".cad" / "server.json"


def _read_info(root):
    try:
        return json.loads(_info_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def server_status(root, port=None):
    info = _read_info(root)
    p = port or (info or {}).get("port") or DEFAULT_PORT
    if not _is_cadchat(p):
        return None
    same = info and info.get("port") == p
    return {"pid": info.get("pid") if same else None, "port": p, "url": f"http://127.0.0.1:{p}/", "started_at": info.get("started") if same else None}


def start_server(root, port=None, wait=15):
    root = Path(root)
    port = port or (_read_info(root) or {}).get("port") or DEFAULT_PORT
    st = server_status(root, port)
    if st:
        return {**st, "started": False}
    if port_open(port):
        raise RuntimeError(f"port {port} is in use by another program (not cadchat); pick another with --port")
    (root / ".cad").mkdir(exist_ok=True)
    log = root / ".cad" / "server.log"
    kw = {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)} \
        if os.name == "nt" else {"start_new_session": True}
    with open(log, "ab") as lf:
        proc = subprocess.Popen([sys.executable, str(SERVER), "--port", str(port), "--root", str(root)], cwd=root,
                                stdin=subprocess.DEVNULL, stdout=lf, stderr=lf, **kw)
    deadline = time.time() + wait
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        if _is_cadchat(port):
            info = _read_info(root) or {}
            return {"pid": info.get("pid", proc.pid), "port": port, "url": f"http://127.0.0.1:{port}/", "started": True}
        time.sleep(0.1)
    tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
    raise RuntimeError(f"the server did not start. Last lines of {log}:\n{tail}")


def stop_server(root):
    """Stop the server recorded for this project. Returns True if one was stopped."""
    info = _read_info(root)
    if not info or not _is_cadchat(info.get("port", DEFAULT_PORT)):
        _info_file(root).unlink(missing_ok=True)
        return False
    port = info["port"]
    try:
        os.kill(info["pid"], signal.SIGTERM)
    except OSError:
        pass
    deadline = time.time() + 5
    while port_open(port) and time.time() < deadline:
        time.sleep(0.1)
    if port_open(port) and hasattr(signal, "SIGKILL"):
        os.kill(info["pid"], signal.SIGKILL)
        time.sleep(0.3)
    _info_file(root).unlink(missing_ok=True)
    return True


def restart_server(root, port=None):
    port = port or (_read_info(root) or {}).get("port") or DEFAULT_PORT
    stop_server(root)
    for _ in range(50):                      # the OS may need a moment to release the port
        if not port_open(port):
            break
        time.sleep(0.1)
    return start_server(root, port)


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
    for name in ("start", "restart", "status"):
        sub.add_parser(name).add_argument("--port", type=int)
    sub.add_parser("stop")
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
        elif a.cmd in ("start", "restart"):
            info = (start_server if a.cmd == "start" else restart_server)(root, a.port)
            print(f"viewer {'started' if info['started'] else 'already running'}: {info['url']} (pid {info['pid']})")
        elif a.cmd == "stop":
            print("stopped" if stop_server(root) else "no cadchat server is running")
        elif a.cmd == "status":
            st = server_status(root, a.port)
            if not st:
                print("not running (start it with: cadchat start)")
                return 1
            print(f"running: {st['url']} (pid {st['pid']})")
        elif a.cmd == "run":
            return subprocess.call([sys.executable, str(root / "parts" / f"{a.name}.py")], cwd=root,
                                   env={**os.environ, "CADCHAT_ROOT": str(root)})
        elif a.cmd == "serve":
            if server_status(root, a.port):
                print(f"already running at http://127.0.0.1:{a.port}/ - use: cadchat restart")
                return 1
            return subprocess.call([sys.executable, str(HERE / "cadserver.py"), "--port", str(a.port), "--root", str(root)])
    except (ValueError, FileExistsError, OSError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
