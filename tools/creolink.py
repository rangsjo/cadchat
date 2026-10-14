"""Live link between cadchat and PTC Creo Parametric (experimental).

  python tools/creolink.py doctor          check every prerequisite and say what to fix
  python tools/creolink.py start           start cadchat, Creo and the bridge, open the viewer (what creo/start.cmd runs)
  python tools/creolink.py run             only the sync loop (server and Creo already running)

How it works: a small Java program (creo/bridge/CreoBridge.java, J-Link asynchronous mode) attaches to a running Creo and
speaks JSON lines. This module drives it: when the model in Creo changes it exports STEP and imports it as a cadchat model;
commands written by the viewer (.cad/creo/commands.jsonl) change parameters in Creo, regenerate and sync back.
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

from lineproc import LineProcess, ProcessError, ProcessTimeout

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SAFE = re.compile(r"[^A-Za-z0-9_-]")


# ---- discovery ------------------------------------------------------------------------------------------------------
@dataclass
class CreoInstall:
    load: Path
    version: tuple
    parametric: Path
    jar: Path | None = None
    dll_dir: Path | None = None
    comm_msg: Path | None = None
    problems: list = field(default_factory=list)


def _first(base, name):
    for p in base.rglob(name):
        return p
    return None


def _inspect(load):
    m = re.search(r"(\d+(?:\.\d+)+)", load.name)
    c = CreoInstall(load=load, version=tuple(int(x) for x in m.group(1).split(".")) if m else (0,),
                    parametric=load / "Parametric" / "bin" / "parametric.exe")
    commons = [d for d in [load / "Common Files", *load.glob("*/Common Files")] if d.is_dir()]
    for base in commons:
        c.jar = c.jar or _first(base / "text", "pfcasync.jar") or _first(base, "pfcasync.jar")
        dll = _first(base, "pfcasyncmt.dll")
        c.dll_dir = c.dll_dir or (dll.parent if dll else None)
        c.comm_msg = c.comm_msg or _first(base, "pro_comm_msg.exe")
    if not c.parametric.exists():
        c.problems.append(f"parametric.exe not found at {c.parametric}")
    if not c.jar:
        c.problems.append(f"pfcasync.jar (J-Link) not found under {load}\\Common Files\\text\\java")
    if not c.dll_dir:
        c.problems.append(f"pfcasyncmt.dll not found under {load}\\Common Files")
    if not c.comm_msg:
        c.problems.append(f"pro_comm_msg.exe not found under {load}\\Common Files")
    return c


def default_roots():
    roots = [Path(os.environ[k]) / "PTC" for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432") if os.environ.get(k)]
    return roots + [Path("C:/PTC"), Path("D:/PTC")]


def discover_creo(roots=None):
    """Newest Creo Parametric under the given roots (default: Program Files\\PTC, C:\\PTC), or the one in CREO_HOME."""
    home = os.environ.get("CREO_HOME")
    if home and Path(home).is_dir():
        return _inspect(Path(home))
    found = []
    for root in (roots if roots is not None else default_roots()):
        root = Path(root)
        if root.is_dir():
            found += [_inspect(d) for d in root.glob("Creo*") if (d / "Parametric" / "bin" / "parametric.exe").exists()]
    return max(found, key=lambda c: c.version) if found else None


def build_env(creo, base):
    """What J-Link asynchronous mode needs: PRO_COMM_MSG_EXE, the pfcasyncmt.dll folder on PATH, pfcasync.jar on the classpath."""
    env = dict(base)
    if creo.comm_msg:
        env["PRO_COMM_MSG_EXE"] = str(creo.comm_msg)
    if creo.dll_dir:
        env["PATH"] = str(creo.dll_dir) + os.pathsep + env.get("PATH", "")
    if creo.jar:
        env["CLASSPATH"] = str(creo.jar) + (os.pathsep + env["CLASSPATH"] if env.get("CLASSPATH") else "")
    return env


@dataclass
class JavaInstall:
    javac: Path
    java: Path


def discover_java():
    """A JDK (javac is needed because the bridge runs from source): JAVA_HOME, PATH, then the usual Windows folders."""
    names = lambda n: [n, n + ".exe"]
    home = os.environ.get("JAVA_HOME")
    if home:
        for jc in names("javac"):
            for j in names("java"):
                if (Path(home) / "bin" / jc).exists() and (Path(home) / "bin" / j).exists():
                    return JavaInstall(Path(home) / "bin" / jc, Path(home) / "bin" / j)
    jc, j = shutil.which("javac"), shutil.which("java")
    if jc and j:
        return JavaInstall(Path(jc), Path(j))
    for base in ("Eclipse Adoptium", "Java", "Microsoft", "Amazon Corretto", "Zulu"):
        for pf in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
            if pf:
                for d in sorted((Path(pf) / base).glob("*"), reverse=True):
                    if (d / "bin" / "javac.exe").exists() and (d / "bin" / "java.exe").exists():
                        return JavaInstall(d / "bin" / "javac.exe", d / "bin" / "java.exe")
    return None


def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), 0.3).close()
        return True
    except OSError:
        return False


def doctor(roots=None, port=8765):
    """[(check, ok, detail)] with a concrete next step for everything that is not ok."""
    out = []
    c = discover_creo(roots)
    out.append(("Creo Parametric installed", c is not None,
                f"{c.load} (version {'.'.join(map(str, c.version))})" if c else "not found; install Creo or set CREO_HOME to its folder (e.g. C:\\Program Files\\PTC\\Creo 10.0.5.0)"))
    missing = lambda what: f"{what} not found" + ("; Creo is missing" if c is None else "")
    out.append(("parametric.exe", bool(c and c.parametric.exists()), str(c.parametric) if c else missing("parametric.exe")))
    out.append(("pfcasync.jar (J-Link)", bool(c and c.jar),
                str(c.jar) if c and c.jar else (f"pfcasync.jar not found under {c.load}\\Common Files\\text\\java; run the Creo installer again and enable the J-Link / API toolkit components" if c else missing("pfcasync.jar"))))
    out.append(("pfcasyncmt.dll", bool(c and c.dll_dir), str(c.dll_dir) if c and c.dll_dir else missing("pfcasyncmt.dll")))
    out.append(("pro_comm_msg.exe", bool(c and c.comm_msg), str(c.comm_msg) if c and c.comm_msg else missing("pro_comm_msg.exe")))
    j = discover_java()
    out.append(("JDK 11+ (javac)", j is not None,
                str(j.javac) if j else "no JDK found; install one: winget install -e --id EclipseAdoptium.Temurin.17.JDK (64-bit), or set JAVA_HOME"))
    src = ROOT / "creo" / "bridge" / "CreoBridge.java"
    out.append(("Bridge source", src.exists(), str(src)))
    try:
        import build123d  # noqa: F401
        out.append(("build123d", True, "importable"))
    except Exception as e:
        out.append(("build123d", False, f"{e}; run: pip install -r requirements.txt"))
    out.append(("cadchat server", True, f"running on port {port}" if port_open(port) else f"not running on port {port}; start will launch it"))
    return out


# ---- bridge process ---------------------------------------------------------------------------------------------------
class BridgeError(Exception):
    pass


class BridgeTimeout(BridgeError):
    pass


class Bridge:
    """Request/reply channel to the Java bridge (or a test double speaking the same JSON lines)."""

    def __init__(self, cmd, env=None, cwd=None, timeout=30.0, log=None):
        self.lp, self.timeout = LineProcess(cmd, env=env, cwd=cwd, log=log), timeout

    @property
    def proc(self):
        return self.lp.last_proc

    def request(self, cmd, timeout=None, **args):
        try:
            reply = self.lp.request({"cmd": cmd, **args}, timeout or self.timeout)
        except ProcessTimeout as e:
            raise BridgeTimeout(str(e))
        except ProcessError as e:
            raise BridgeError(str(e))
        if not reply.get("ok"):
            raise BridgeError(reply.get("error", "unknown error"))
        return reply

    def close(self):
        self.lp.stop()


# ---- the sync loop ----------------------------------------------------------------------------------------------------
def model_id(name):
    stem = SAFE.sub("_", name.split(".")[0]).strip("_-")
    return "creo_" + (stem or "model")


class CreoLink:
    def __init__(self, root, bridge, importer=None, poll=2.0, clock=time.time):
        self.root, self.bridge, self.poll, self.clock = Path(root), bridge, poll, clock
        self.dir = self.root / ".cad" / "creo"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.importer = importer or self._default_importer
        self.auto_sync = True
        self.connected, self.model, self.params = False, None, []
        self.last_sync, self.last_error, self.last_result = None, "", None
        self._synced = (None, None)
        cmds = self.dir / "commands.jsonl"
        self._offset = cmds.stat().st_size if cmds.exists() else 0          # ignore commands left over from an earlier session

    @staticmethod
    def _default_importer(path, name):
        import exchange
        return exchange.import_to_model(path, name)

    # -- state shared with the viewer through the server
    def write_state(self):
        st = {"connected": self.connected, "model": self.model, "model_id": model_id(self.model) if self.model else None,
              "auto_sync": self.auto_sync, "params": self.params, "last_sync": self.last_sync,
              "last_error": self.last_error, "last_result": self.last_result, "updated": self.clock()}
        tmp = self.dir / "state.tmp"
        tmp.write_text(json.dumps(st), encoding="utf-8")
        tmp.replace(self.dir / "state.json")

    # -- one iteration
    def step(self):
        events = []
        try:
            status = self._status()
            self.connected = bool(status)
            if status:
                self.model, fp = status.get("model"), status.get("fingerprint", "")
                if self._process_commands(events):                          # commands change Creo: look again
                    status = self.bridge.request("status")
                    self.model, fp = status.get("model"), status.get("fingerprint", "")
                if self.model and self.auto_sync and (self.model, fp) != self._synced:
                    self._sync(events)
        except BridgeError as e:
            self.last_error = str(e)
        self.write_state()
        return events

    def _status(self):
        r = self.bridge.request("status")
        if not r.get("connected"):
            try:
                self.bridge.request("connect", timeout=60)
                r = self.bridge.request("status")
            except BridgeError as e:
                self.last_error = f"Creo not reachable: {e}"
                return None
        return r

    def _sync(self, events):
        r = self.bridge.request("status")
        self.model, fp = r.get("model"), r.get("fingerprint", "")
        if not self.model:
            raise BridgeError("no model is open in Creo")
        path = self.dir / f"{SAFE.sub('_', self.model.split('.')[0]) or 'model'}.step"
        self.bridge.request("export_step", timeout=120, path=str(path))
        self._synced = (self.model, fp)
        try:
            self.importer(path, model_id(self.model))
            self.last_error = ""
            events.append(f"synced {self.model}")
        except Exception as e:                                              # a bad STEP must not stop the loop
            self.last_error = f"import failed: {e}"
        self.last_sync = self.clock()
        self.params = self.bridge.request("params").get("params", [])

    def _process_commands(self, events):
        f = self.dir / "commands.jsonl"
        if not f.exists():
            return False
        with open(f, "rb") as fh:
            fh.seek(self._offset)
            data = fh.read()
        self._offset += len(data)
        ran = False
        for line in data.decode("utf-8", "replace").splitlines():
            try:
                self._run(json.loads(line), events)
                ran = True
            except ValueError:
                continue
        return ran

    def _run(self, c, events):
        cmd = c.get("cmd")
        try:
            if cmd == "sync":
                self._sync(events)
            elif cmd == "set":
                self.bridge.request("set", name=c["name"], value=c["value"])
                self.bridge.request("regenerate", timeout=120)
                self._sync(events)
            elif cmd == "regenerate":
                self.bridge.request("regenerate", timeout=120)
                self._sync(events)
            elif cmd == "auto_sync":
                self.auto_sync = bool(c.get("value"))
            else:
                raise ValueError(f"unknown command '{cmd}'")
            self.last_result = {"id": c.get("id"), "cmd": cmd, "ok": True, "message": "done", "time": self.clock()}
        except (BridgeError, ValueError, KeyError) as e:
            self.last_result = {"id": c.get("id"), "cmd": cmd, "ok": False, "message": str(e), "time": self.clock()}

    def run(self, log=print):
        while True:
            for e in self.step():
                log(e)
            time.sleep(self.poll)


# ---- command line -----------------------------------------------------------------------------------------------------
def start(a):
    creo = discover_creo()
    if creo is None or creo.problems:
        print("Creo is not ready:")
        for p in (creo.problems if creo else ["Creo Parametric not found (set CREO_HOME)"]):
            print("  -", p)
        return 4
    java = discover_java()
    if java is None:
        print("No JDK found (the bridge runs from source). Install one: winget install -e --id EclipseAdoptium.Temurin.17.JDK")
        return 3
    children = []
    if not port_open(a.port):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        children.append(subprocess.Popen([sys.executable, str(HERE / "cadserver.py"), "--port", str(a.port), "--root", str(ROOT)],
                                         cwd=ROOT, creationflags=flags))
        for _ in range(50):
            if port_open(a.port):
                break
            time.sleep(0.2)
    log = ROOT / ".cad" / "creo" / "bridge.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    bridge = Bridge([str(java.java), "-cp", str(creo.jar), str(ROOT / "creo" / "bridge" / "CreoBridge.java")],
                    env=build_env(creo, os.environ), cwd=ROOT, log=log, timeout=30)
    launched = False
    deadline = time.time() + a.wait
    print(f"Creo {'.'.join(map(str, creo.version))} at {creo.load}")
    while True:
        try:
            bridge.request("connect", timeout=60)
            break
        except BridgeError as e:
            if not launched and not a.no_launch:
                print("Creo is not running: starting it (this takes a minute; log in / pick a licence if asked)...")
                subprocess.Popen([str(creo.parametric)], cwd=ROOT / "creo" / "workdir")
                launched = True
            if time.time() > deadline:
                print(f"Could not connect to Creo within {a.wait} s: {e}\nSee creo/README.md (troubleshooting) and run: creo\\start.cmd doctor")
                return 5
            print(".", end="", flush=True)
            time.sleep(5)
    print(f"\nConnected to Creo. Viewer: http://127.0.0.1:{a.port}/  (Creo tab)")
    if not a.no_browser:
        webbrowser.open(f"http://127.0.0.1:{a.port}/#creo")
    link = CreoLink(ROOT, bridge)
    try:
        link.run(log=lambda e: print(time.strftime("%H:%M:%S"), e, flush=True))
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()
        for ch in children:
            ch.terminate()
    return 0


def main(argv=None):
    sys.path.insert(0, str(HERE))
    ap = argparse.ArgumentParser(prog="creolink")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("doctor", "start", "run"):
        p = sub.add_parser(name)
        p.add_argument("--port", type=int, default=8765)
        p.add_argument("--creo", help="Creo load point (same as CREO_HOME)")
        p.add_argument("--no-launch", action="store_true", help="never start Creo, only attach to a running one")
        p.add_argument("--no-browser", action="store_true")
        p.add_argument("--wait", type=int, default=300, help="seconds to wait for Creo to accept the connection")
    a = ap.parse_args(argv)
    if a.creo:
        os.environ["CREO_HOME"] = a.creo
    if a.cmd == "doctor":
        results = doctor(port=a.port)
        for name, ok, detail in results:
            print(f"[{'ok' if ok else 'FAIL'}] {name}: {detail}")
        return 0 if all(ok for _, ok, _ in results) else 1
    return start(a)


if __name__ == "__main__":
    raise SystemExit(main())
