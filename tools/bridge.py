"""Per-message bridge: every chat message of the viewer is run through an AI agent's non-interactive mode once ("claude -p", "copilot -p",
"codex exec", "gemini -p", or your own command) and the agent's answer is posted as the chat reply.

Why: it works with any agent that can edit files and run commands (no live session or special watch tool needed), and nothing from earlier
messages is resent, so the cost of a message does not grow with the length of the conversation.

  python tools/cadchat.py bridge [--provider copilot] [--command "myagent --x"]
"""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import cadreply
import launcher
import providers
import settings
from cadwatch import Watcher

MAX_REPLY = 3500


def _g(v):
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def build_prompt(root, m):
    """Everything the agent needs for one message: the request, what the user was looking at, and the rules of the project."""
    root = Path(root)
    lines = [f"You are the assistant of a code-CAD viewer (cadchat). The user sent a message from the viewer's chat popup.",
             f"Project folder: {root} (model scripts in parts/; build one with ./cadchat run NAME; the viewer reloads by itself).",
             "Follow AGENTS.md in the current folder for the conventions (mm, z up, PARAMS block, name every part, numbers before claims).", "",
             f"User request: {m.get('text', '')}"]
    ctx = []
    if m.get("model"):
        ctx.append(f"model: {m['model']}")
    if m.get("parts") or m.get("part"):
        ctx.append("selected part(s): " + ", ".join(m.get("parts") or [m["part"]]))
    pose = {k: v for k, v in (m.get("pose") or {}).items() if v}
    if pose:
        ctx.append("pose (joints not at zero): " + ", ".join(f"{k}={_g(v)}" for k, v in pose.items()))
    if m.get("constraint"):
        ctx.append(f"constraint selected: {m['constraint']}")
    if m.get("measure"):
        ctx.append(f"measurement: {m['measure']}")
    if m.get("point"):
        ctx.append(f"clicked point (mm): {m['point']}, surface normal {m.get('normal')}")
    if ctx:
        lines += ["Context from the viewer:"] + [f"- {c}" for c in ctx]
    if m.get("shot"):
        lines.append(f"- screenshot of the viewer (look at it if you can read images): {root / m['shot']}")
    lines += ["", "Make the change in the model script, rebuild it, check the numbers (sizes, collisions) and state your interpretation if the request was ambiguous.",
              "Your final answer (2 to 5 sentences: what changed, the numbers, caveats) is posted to the chat automatically: do not call cadreply yourself and do not repeat the request."]
    return "\n".join(lines)


class Bridge:
    def __init__(self, root, provider=None, command=None, timeout=900, quiet=True):
        s = settings.load()
        self.root = Path(root)
        self.provider = provider or s["provider"]
        self.command = s["assistant_cmd"] if command is None else command
        self.timeout, self.quiet = timeout, quiet
        self.queue = []

    def _reply(self, text, model=None, status=False):
        cadreply.reply(self.root, text, status=status, model=model)

    def handle(self, m):
        if m.get("role") != "user":
            return
        model = m.get("model")
        self._reply("Working on it…", model, status=True)
        try:
            argv = providers.oneshot_argv(self.provider, build_prompt(self.root, m), self.command)
        except (KeyError, ValueError) as e:
            self._reply(f"The assistant is not set up: {e}. Open Help ▸ Setup wizard.", model)
            return
        env = {**os.environ, "CADCHAT_ROOT": str(self.root), "CADCHAT_TOOLS": str(launcher.APP / "tools")}
        try:
            r = subprocess.run(argv, cwd=launcher.APP, env=env, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            self._reply(f"The assistant timed out after {self.timeout:g} s on this message. Try a smaller step, or raise the time limit.", model)
            return
        except OSError as e:
            self._reply(f"Could not start the assistant command ({argv[0]}): {e}. Install it and sign in: Help ▸ Setup wizard.", model)
            return
        out = (r.stdout or "").strip()
        if r.returncode != 0:
            tail = ((r.stderr or "").strip() or out)[-600:]
            self._reply(f"The assistant command failed (exit {r.returncode}): {tail}", model)
            return
        text = out or "(the assistant finished without a text answer)"
        self._reply(text if len(text) <= MAX_REPLY else text[:MAX_REPLY] + "\n… (shortened)", model)

    def run(self, stop=None, poll=0.4, log=print):
        stop = stop or threading.Event()
        w = Watcher(self.root, out=lambda line: self.queue.append(json.loads(line)))
        w.start()

        def beat():
            while not stop.is_set():
                w.beat()
                stop.wait(2)
        threading.Thread(target=beat, daemon=True).start()
        try:
            while not stop.is_set():
                w.poll()
                while self.queue and not stop.is_set():
                    m = self.queue.pop(0)
                    if not self.quiet:
                        log(f"message: {m.get('text', '')[:80]}")
                    self.handle(m)
                stop.wait(poll)
        finally:
            stop.set()
            w.stop()
