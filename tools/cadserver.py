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
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import cadchat
import history
import joints
import launcher
import projects
import providers
import settings
import share
import usage
from cadwatch import read_jsonl, unanswered
from lineproc import LineProcess, ProcessError

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
        self.root, self.lp, self.started = Path(root), None, 0.0

    @property
    def pid(self):
        return self.lp.pid if self.lp else None

    def start(self):
        self.stop()
        env = {**os.environ, "CADCHAT_ROOT": str(self.root), "CADCHAT_TOOLS": str(HERE)}
        (self.root / ".cad").mkdir(exist_ok=True)
        self.lp = LineProcess([sys.executable, str(HERE / "cadworker.py")], env=env, cwd=self.root, log=self.root / ".cad" / "worker.log")
        self.lp.start()
        self.started = time.time()

    def stop(self):
        if self.lp:
            self.lp.stop()
        self.lp = None

    def _stale(self):
        return any(f.stat().st_mtime > self.started for f in HERE.glob("*.py"))

    def request(self, req, timeout=300):
        if self.lp is None or self.lp.pid is None or self._stale():
            self.start()
        try:
            return self.lp.request(req, timeout)
        except ProcessError as e:
            return {"ok": False, "error": f"the build worker stopped ({e}); it will be restarted", "out": ""}


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

    def clear_chat(self):
        """Archive the conversation (.cad/chat-archive/<time>.jsonl), start empty and reset the assistant session: one the viewer started is
        replaced by a fresh one with an empty context (so old screenshots and errors are not carried and paid for again); one started by
        hand is told through the inbox that everything earlier is closed."""
        with self.lock:
            f = self.cad / "chat.jsonl"
            msgs = read_jsonl(f)
            name = None
            if msgs:
                arch = self.cad / "chat-archive"
                arch.mkdir(exist_ok=True)
                name = time.strftime("%Y%m%d-%H%M%S") + ".jsonl"
                (arch / name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                f.write_text("", encoding="utf-8")
                (self.cad / "seen.jsonl").write_text("", encoding="utf-8")
        assistant = launcher.restart_assistant(self.root)
        if msgs and assistant == "none":
            with open(self.cad / "inbox.jsonl", "a", encoding="utf-8") as ib:
                ib.write(json.dumps({"id": time.strftime("%H%M%S") + "-clear", "role": "system",
                                     "text": "The user cleared the chat: all earlier messages are closed, no need to answer them or keep them in mind. "
                                             "If you can, end this session and let the user start a fresh one: its context still holds the old messages and screenshots."}) + "\n")
        return {"ok": True, "archived": len(msgs), "file": f".cad/chat-archive/{name}" if name else None, "assistant": assistant}

    # ---- menu backend ---------------------------------------------------------------------------------------
    def projects_list(self):
        cur = str(self.root)
        if projects.is_project(self.root):
            projects.touch(self.root)
        known = projects.known_projects()
        out = [{**p, "current": p["path"] == cur} for p in known]
        if not any(p["current"] for p in out):
            out.insert(0, {"path": cur, "name": self.name, "current": True, "last_used": time.time()})
        return {"projects": out, "projects_dir": str(settings.projects_dir())}

    def project_new(self, name):
        name = str(name or "").strip()
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$", name):
            raise Problem(200, "name: letters, digits, spaces, _ or - (start with a letter or digit)")
        base = settings.projects_dir()
        path = base / re.sub(r"\s+", "-", name)
        if not path.resolve().is_relative_to(base):
            raise Problem(200, "bad project name")
        try:
            projects.init_project(path, name)
        except FileExistsError:
            raise Problem(200, f"a project named '{name}' already exists in {base}")
        return {"ok": True, **self._serve(path)}

    def project_open(self, path):
        p = Path(str(path or "")).expanduser().resolve()
        if not projects.is_project(p):
            raise Problem(200, f"{p} is not a cadchat project")
        projects.touch(p)
        return {"ok": True, **self._serve(p)}

    def _serve(self, path):
        if Path(path).resolve() == self.root:
            return {"url": None, "port": None}
        try:
            info = cadchat.start_server(path)
        except RuntimeError as e:
            raise Problem(200, str(e))
        return {"url": info["url"], "port": info["port"]}

    def model_new(self, d):
        name = str(d.get("name") or "")
        try:
            if d.get("library"):
                projects.add_from_library(str(d["library"]), self.root, name or None)
                name = name or str(d["library"])
            else:
                cadchat.create(str(d.get("kind")), name, self.root)
        except (ValueError, FileExistsError) as e:
            raise Problem(200, str(e))
        self.build(name)
        return {"ok": True, "id": name}

    def save_version(self, mid, note):
        script = self.script_of(mid)
        sid = history.snapshot(self.root, mid, script.relative_to(self.root).as_posix(), note=str(note or "Saved version")[:200], force=True)
        return {"ok": True, "id": sid}

    def exports(self, mid):
        d = self.root / "exports"
        if not ID_RE.match(mid or "") or not d.is_dir():
            return []
        return [{"name": f.name, "size": f.stat().st_size} for f in sorted(d.iterdir()) if f.is_file() and f.name.startswith(mid)]

    def export_file(self, name):
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$", name or ""):
            raise Problem(400, "bad file name")
        f = (self.root / "exports" / name).resolve()
        if not f.is_relative_to((self.root / "exports").resolve()) or not f.is_file():
            raise Problem(404, "no such export")
        return f

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
    # ---- Creo link (state and commands are files shared with tools/creolink.py) --------------------------------
    def creo_state(self):
        f = self.cad / "creo" / "state.json"
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

    def creo_command(self, d):
        cmd = d.get("cmd")
        if cmd not in ("sync", "set", "regenerate", "auto_sync"):
            raise Problem(400, "unknown command")
        out = {"cmd": cmd, "id": secrets.token_hex(4)}
        if cmd == "set":
            name, value = d.get("name"), d.get("value")
            if not isinstance(name, str) or not 0 < len(name) <= 80 or not name.isprintable():
                raise Problem(400, "bad parameter name")
            if isinstance(value, bool) or not isinstance(value, (int, float, str)) or (isinstance(value, str) and len(value) > 200):
                raise Problem(400, "value must be a number or a short text")
            out.update(name=name, value=value)
        if cmd == "auto_sync":
            if not isinstance(d.get("value"), bool):
                raise Problem(400, "auto_sync needs true or false")
            out["value"] = d["value"]
        (self.cad / "creo").mkdir(exist_ok=True)
        with open(self.cad / "creo" / "commands.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(out) + "\n")
        return {"ok": True, "id": out["id"]}

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
            if p == "/api/settings":
                return self._json(settings.load())
            if p == "/api/projects":
                return self._json(app.projects_list())
            if p == "/api/exports":
                return self._json(app.exports(q.get("m", [""])[0]))
            if p == "/api/export/file":
                f = app.export_file(q.get("name", [""])[0])
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            if p == "/api/usage":
                dirs = [d.strip() for d in settings.load()["usage_dirs"].split(",") if d.strip()]
                return self._json(usage.collect(app.root, dirs=dirs or None))
            if p == "/api/providers":
                s = settings.load()
                keep = ("id", "name", "binary", "listens", "subscription", "install", "login", "agent_file")
                return self._json({"providers": [{k: v for k, v in pr.items() if k in keep} for pr in providers.catalog()],
                                   "current": {k: s[k] for k in ("provider", "assistant_mode", "setup_done")}})
            if p == "/api/library":
                return self._json(projects.library_list())
            if p == "/api/joints":
                try:
                    t = float(q.get("t", ["18"])[0])
                except ValueError:
                    raise Problem(400, "bad thickness")
                return self._json(joints.catalog(t))
            if p == "/api/assistant":
                return self._json(app.assistant_state())
            if p == "/api/creo":
                return self._json(app.creo_state())
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
                if p == "/api/creo/command":
                    return self._json(app.creo_command(body))
                if p == "/api/build":
                    app.build(body.get("script"))
                    return self._json({"ok": True})
                vals = {str(k): float(v) for k, v in (body.get("values") or {}).items()}
                if p == "/api/check":
                    return self._json({"ok": True, "collisions": app.check(body.get("m"), vals)})
                if p == "/api/providers/test":
                    try:
                        return self._json({"ok": True, **providers.detect(str(body.get("id")))})
                    except KeyError:
                        raise Problem(200, "unknown provider")
                if p == "/api/chat/clear":
                    return self._json(app.clear_chat())
                if p == "/api/share/build":
                    mid = body.get("m")
                    files = share.build_site(app.root, app.root / "share", [mid] if mid else None)
                    return self._json({"ok": True, "files": [f.name for f in files], "path": str(app.root / "share")})
                if p == "/api/settings":
                    try:
                        return self._json({"ok": True, "settings": settings.save(body)})
                    except ValueError as e:
                        raise Problem(200, str(e))
                if p == "/api/project/new":
                    return self._json(app.project_new(body.get("name")))
                if p == "/api/project/open":
                    return self._json(app.project_open(body.get("path")))
                if p == "/api/model/new":
                    return self._json(app.model_new(body))
                if p == "/api/version/save":
                    return self._json(app.save_version(body.get("m"), body.get("note")))
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
