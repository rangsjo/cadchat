"""cadchat server: serves the 3D viewer, the published models and a chat bridge.

  python tools/cadserver.py [--port 8765] [--root PROJECT_DIR]

Models live in <root>/.cad/models/<id>/ (see cadview.publish_kinematic). Chat messages from the viewer are appended to
<root>/.cad/inbox.jsonl (watched by the assistant) and <root>/.cad/chat.jsonl (shown in the viewer);
the assistant answers with tools/cadreply.py.
"""
import argparse
import base64
import json
import os
import re
import runpy
import secrets
import select
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import history
import launcher
from cadwatch import read_jsonl, unanswered

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css"}


def _project_name(root):
    try:
        return json.loads((Path(root) / "cadproject.json").read_text(encoding="utf-8")).get("name") or Path(root).name
    except (OSError, ValueError):
        return Path(root).name


class Problem(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status, self.msg = status, msg


class Worker:
    """Talks to tools/cadworker.py; started on first use, restarted if it dies, times out or tools/*.py changed."""

    def __init__(self, root):
        self.root, self.proc, self.pid, self.started = Path(root), None, None, 0.0

    def start(self):
        self.stop()
        log = open(self.root / ".cad" / "worker.log", "ab")
        env = {**os.environ, "CADCHAT_ROOT": str(self.root), "CADCHAT_TOOLS": str(HERE)}
        self.proc = subprocess.Popen([sys.executable, str(HERE / "cadworker.py")], cwd=self.root, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
        self.pid, self.started = self.proc.pid, time.time()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        self.proc, self.pid = None, None

    def _stale(self):
        return any(f.stat().st_mtime > self.started for f in HERE.glob("*.py"))

    def _readline(self, timeout):
        buf, fd, end = b"", self.proc.stdout.fileno(), time.time() + timeout
        while not buf.endswith(b"\n"):
            left = end - time.time()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                raise TimeoutError
            chunk = os.read(fd, 65536)
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    def request(self, req, timeout=300):
        if self.proc is None or self.proc.poll() is not None or self._stale():
            self.start()
        try:
            self.proc.stdin.write((json.dumps(req) + "\n").encode())
            self.proc.stdin.flush()
            return json.loads(self._readline(timeout))
        except (TimeoutError, EOFError, BrokenPipeError):
            self.stop()
            return {"ok": False, "error": "the build worker stopped or timed out; it will be restarted", "out": ""}


class App:
    def __init__(self, root, port):
        self.root = Path(root).resolve()
        self.cad = self.root / ".cad"
        self.name = _project_name(self.root)
        (self.cad / "shots").mkdir(parents=True, exist_ok=True)
        self.token = self._load_token()
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.lock = threading.Lock()
        self._scripts = {}
        self._meta = {}
        self.worker = Worker(self.root)

    def _load_token(self):
        """Persisted in .cad/token so pages that are already open keep working after the server is restarted."""
        f = self.cad / "token"
        try:
            t = f.read_text(encoding="utf-8").strip()
            if len(t) >= 16:
                return t
        except OSError:
            pass
        t = secrets.token_urlsafe(16)
        f.write_text(t, encoding="utf-8")
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
        return t

    # ---- models ---------------------------------------------------------------------------------------------
    def mdir(self, mid):
        if not mid or not ID_RE.match(mid):
            raise Problem(400, "bad model id")
        return self.cad / "models" / mid

    def stamps(self):
        """{model id: microseconds since epoch of model.json}; stats files only, never parses them."""
        return {f.parent.name: f.stat().st_mtime_ns // 1000 for f in (self.cad / "models").glob("*/model.json")}

    def models(self):
        stamps, out = self.stamps(), []
        for mid in sorted(stamps):
            c = self._meta.get(mid)
            if not c or c[0] != stamps[mid]:                     # parse only when the file changed
                try:
                    m = json.loads((self.cad / "models" / mid / "model.json").read_text(encoding="utf-8"))
                    c = (stamps[mid], len(m["parts"]), len(m["joints"]))
                except (ValueError, KeyError):
                    c = (stamps[mid], 0, 0)
                self._meta[mid] = c
            out.append({"id": mid, "built": True, "mtime": stamps[mid], "parts": c[1], "joints": c[2]})
        for f in sorted((self.root / "parts").glob("*.py")):
            if not f.stem.startswith("_") and f.stem not in stamps and ID_RE.match(f.stem):
                out.append({"id": f.stem, "built": False})
        latest = max(stamps, key=stamps.get) if stamps else None
        return {"models": out, "latest": latest}

    def script_of(self, mid):
        d = self.mdir(mid)
        rec = d / "script"
        cand = (self.root / rec.read_text(encoding="utf-8").strip()) if rec.exists() else self.root / "parts" / f"{mid}.py"
        cand = cand.resolve()
        if not cand.is_relative_to((self.root / "parts").resolve()) or not cand.is_file():
            raise Problem(404, "script not found")
        return cand

    def run_script(self, script):
        r = self.worker.request({"script": str(script)})
        if not r["ok"]:
            raise Problem(200, r["error"] or r.get("out", "")[-600:])

    def build(self, stem):
        if not stem or not ID_RE.match(stem):
            raise Problem(400, "bad script name")
        script = self.root / "parts" / f"{stem}.py"
        if not script.is_file():
            raise Problem(404, "no such script")
        with self.lock:
            self.run_script(script)

    def import_file(self, name, ext, data):
        if not ID_RE.match(name or "") or ext not in ("step", "stp", "stl"):
            raise Problem(400, "bad model name or file type")
        d = self.cad / "imports"
        d.mkdir(exist_ok=True)
        f = d / f"{name}.{ext}"
        f.write_bytes(data)
        with self.lock:
            r = self.worker.request({"import": str(f), "name": name})
        if not r["ok"]:
            raise Problem(200, r["error"])

    def check(self, mid, values):
        d = self.mdir(mid)
        if not (d / "model.json").exists():
            raise Problem(404, "no such model")
        rec = d / "script"
        if not rec.exists() or not rec.read_text(encoding="utf-8").strip():          # imported models have no script: nothing to check
            return []
        script = self.script_of(mid)
        pf = self.mdir(mid) / "params.json"
        stamp = (script.stat().st_mtime_ns, pf.stat().st_mtime_ns if pf.exists() else 0)
        with self.lock:
            cached = self._scripts.get(script)
            if not cached or cached[0] != stamp:
                ns = runpy.run_path(str(script), run_name="cadcheck")
                cached = (stamp, ns.get("check_pose"))
                self._scripts[script] = cached
            fn = cached[1]
            return fn(values) if fn else []

    def set_params(self, mid, values):
        script = self.script_of(mid)
        f = self.mdir(mid) / "params.json"
        old = f.read_text(encoding="utf-8") if f.exists() else None
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(values), encoding="utf-8")
        try:
            with self.lock:
                self.run_script(script)
        except Problem:
            f.write_text(old, encoding="utf-8") if old is not None else f.unlink()
            raise

    def restore(self, mid, sid):
        script = self.script_of(mid)
        with self.lock:
            try:
                history.restore(self.root, mid, sid, script.relative_to(self.root).as_posix())
            except KeyError:
                raise Problem(404, "no such snapshot")
            self.run_script(script)

    # ---- assistant presence and delivery state -----------------------------------------------------------------
    def assistant_state(self):
        try:
            hb = json.loads((self.cad / "assistant.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            hb = {}
        beat = hb.get("beat")
        listening = bool(beat) and hb.get("listening", True) is not False and time.time() - float(beat) < 8
        pending = len(unanswered(read_jsonl(self.cad / "chat.jsonl"), collapse=False))
        return {"listening": listening, "last_seen": beat, "since": hb.get("since"), "pending": pending}

    def chat(self, model=None):
        msgs = read_jsonl(self.cad / "chat.jsonl")
        if model:
            msgs = [m for m in msgs if m.get("model") in (model, None)]
        seen = {m.get("id") for m in read_jsonl(self.cad / "seen.jsonl")}
        for i, m in enumerate(msgs):
            if m.get("role") != "user":
                continue
            later = [x.get("role") for x in msgs[i + 1:]]
            m["state"] = "answered" if "assistant" in later else "queued" if m.get("id") not in seen else "working" if "status" in later else "seen"
        return msgs

    # ---- chat -----------------------------------------------------------------------------------------------
    def message(self, d):
        mid = time.strftime("%H%M%S") + "-" + secrets.token_hex(2)
        shot = None
        if str(d.get("shot", "")).startswith("data:image/png;base64,"):
            shot = f".cad/shots/{mid}.png"
            (self.root / shot).write_bytes(base64.b64decode(d["shot"].split(",", 1)[1]))
        msg = {"id": mid, "role": "user", "text": str(d.get("text", ""))[:4000], "model": d.get("m"),
               "pose": d.get("pose"), "part": d.get("part"), "parts": d.get("parts"), "measure": d.get("measure"),
               "constraint": d.get("constraint"), "point": d.get("point"), "normal": d.get("normal"), "shot": shot}
        for name in ("chat.jsonl", "inbox.jsonl"):
            with open(self.cad / name, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg) + "\n")
        return {"ok": True, "id": mid}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            body = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj))

        def _guard(self, fn):
            try:
                fn()
            except Problem as p:
                if p.status == 200:
                    self._json({"ok": False, "error": p.msg})
                else:
                    self._json({"ok": False, "error": p.msg}, p.status)
            except Exception as e:                                  # keep the server alive on bad scripts
                self._json({"ok": False, "error": str(e)[:600]})

        def do_GET(self):
            if self.headers.get("Host", "") not in app.hosts:
                return self._send(403, "bad host", "text/plain")
            u = urlparse(self.path)
            q = parse_qs(u.query)
            p = u.path
            if p.startswith("/api/"):
                return self._guard(lambda: self._api_get(p, q))
            rel = "index.html" if p == "/" else unquote(p).lstrip("/")
            f = (STATIC / rel).resolve()
            if not f.is_relative_to(STATIC.resolve()) or f.suffix not in TYPES or not f.is_file():
                return self._send(404, "not found", "text/plain")
            body = f.read_text(encoding="utf-8").replace("__TOKEN__", app.token) if rel == "index.html" else f.read_bytes()
            self._send(200, body, TYPES[f.suffix])

        def _api_get(self, p, q):
            if p == "/api/models":
                return self._json(app.models())
            if p == "/api/version":
                stamps = app.stamps()
                return self._json({"models": stamps, "latest": max(stamps, key=stamps.get) if stamps else None,
                                   "project": str(app.root), "name": app.name})
            if p == "/api/model":
                f = app.mdir(q.get("m", [""])[0]) / "model.json"
                if not f.exists():
                    raise Problem(404, "no such model")
                return self._send(200, f.read_text(encoding="utf-8"))
            if p == "/api/assistant":
                return self._json(app.assistant_state())
            if p == "/api/chat":
                return self._json(app.chat(q.get("m", [""])[0] or None))
            if p == "/api/history":
                try:
                    return self._json(history.list_history(app.root, q.get("m", [""])[0]))
                except ValueError:
                    raise Problem(400, "bad model id")
            raise Problem(404, "not found")

        def do_POST(self):
            if self.headers.get("Host", "") not in app.hosts or self.headers.get("X-CAD-Token") != app.token:
                return self._send(403, "forbidden", "text/plain")
            n = int(self.headers.get("Content-Length", 0))
            u = urlparse(self.path)
            if u.path == "/api/import":
                if n > 200_000_000:
                    return self._send(413, "too large", "text/plain")
                q = parse_qs(u.query)
                data = self.rfile.read(n)
                return self._guard(lambda: (app.import_file(q.get("name", [""])[0], q.get("ext", [""])[0].lower(), data),
                                            self._json({"ok": True})))
            if n > 8_000_000:
                return self._send(413, "too large", "text/plain")
            body = json.loads(self.rfile.read(n) or b"{}")
            p = u.path

            def run():
                if p == "/api/message":
                    return self._json(app.message(body))
                if p == "/api/build":
                    app.build(body.get("script"))
                    return self._json({"ok": True})
                vals = {str(k): float(v) for k, v in (body.get("values") or {}).items()}
                if p == "/api/check":
                    return self._json({"ok": True, "collisions": app.check(body.get("m"), vals)})
                if p == "/api/assistant/start":
                    return self._json({"ok": True, "state": launcher.start_assistant(app.root)})
                if p == "/api/restore":
                    app.restore(body.get("m"), str(body.get("id", "")))
                    return self._json({"ok": True})
                if p == "/api/params":
                    app.set_params(body.get("m"), vals)
                    return self._json({"ok": True})
                raise Problem(404, "not found")
            self._guard(run)
    return Handler


def make_server(root, port=8765):
    """Returns (httpd, token). port=0 picks a free port (tests)."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), lambda *a, **k: None)
    app = App(root, httpd.server_address[1])
    httpd.RequestHandlerClass = make_handler(app)
    httpd.app = app
    return httpd, app.token


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--root", default=os.environ.get("CADCHAT_ROOT") or str(__import__("projects").resolve_project()))
    a = ap.parse_args()
    os.environ["CADCHAT_ROOT"] = str(Path(a.root).resolve())
    try:
        srv, _ = make_server(a.root, a.port)
    except OSError as e:
        print(f"cannot listen on port {a.port}: {e}. Another program (or another cadchat) uses it: ./cadchat status, ./cadchat restart", file=sys.stderr)
        raise SystemExit(2)
    info = Path(a.root) / ".cad" / "server.json"
    info.write_text(json.dumps({"pid": os.getpid(), "port": srv.server_address[1], "started": time.time()}), encoding="utf-8")
    import atexit
    atexit.register(lambda: info.unlink(missing_ok=True))
    threading.Thread(target=srv.app.worker.start, daemon=True).start()          # pre-warm: first rebuild is fast too
    print(f"cadchat on http://127.0.0.1:{srv.server_address[1]}  (project {Path(a.root).resolve()})", flush=True)
    srv.serve_forever()
