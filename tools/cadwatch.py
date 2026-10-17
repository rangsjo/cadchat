"""The message watch the assistant runs (as a Monitor): forwards viewer messages and tells the viewer someone is listening.

  python tools/cadwatch.py              run until killed; every line printed is one viewer message as JSON

- On start it replays messages nobody answered yet (for example after an earlier watch expired), identical repeats collapsed.
- It then forwards every new line of .cad/inbox.jsonl once, and records each in .cad/seen.jsonl (the viewer shows "seen").
- It writes a heartbeat to .cad/assistant.json every couple of seconds; the viewer shows "assistant listening" from it.
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPLAY_KEYS = ("text", "model", "part", "parts", "constraint")


def read_jsonl(path):
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def unanswered(chat, collapse=True):
    """User messages after the last assistant reply. A status line ("working on it") does not count as an answer."""
    last = max((i for i, m in enumerate(chat) if m.get("role") == "assistant"), default=-1)
    open_ = [m for m in chat[last + 1:] if m.get("role") == "user"]
    if not collapse:
        return open_
    groups = {}
    for m in open_:
        key = json.dumps([m.get(k) for k in REPLAY_KEYS], sort_keys=True)
        groups.setdefault(key, []).append(m)
    out = []
    for g in groups.values():
        latest = dict(g[-1])
        if len(g) > 1:
            latest["repeats"] = len(g)
        out.append(latest)
    return sorted(out, key=lambda m: [x.get("id") for x in open_].index(m["id"]))


class Watcher:
    def __init__(self, root, out=print, clock=time.time):
        self.cad = Path(root) / ".cad"
        self.out, self.clock = out, clock
        self.since = None
        self._offset = 0
        self._emitted = set()

    def _write_heartbeat(self, listening=True):
        self.cad.mkdir(parents=True, exist_ok=True)
        tmp = self.cad / "assistant.tmp"
        tmp.write_text(json.dumps({"beat": self.clock(), "since": self.since, "pid": os.getpid(), "listening": listening}), encoding="utf-8")
        tmp.replace(self.cad / "assistant.json")

    def beat(self):
        self._write_heartbeat(True)

    def _emit(self, msg, **extra):
        self._emitted.add(msg.get("id"))
        self.out(json.dumps({**msg, **extra}))
        with open(self.cad / "seen.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": msg.get("id"), "t": self.clock()}) + "\n")

    def start(self):
        self.cad.mkdir(parents=True, exist_ok=True)
        self.since = self.clock()
        inbox = self.cad / "inbox.jsonl"
        self._offset = inbox.stat().st_size if inbox.exists() else 0       # take the offset first: nothing can slip through
        for m in unanswered(read_jsonl(self.cad / "chat.jsonl")):
            self._emit(m, backlog=True)
        self._write_heartbeat(True)

    def poll(self):
        inbox = self.cad / "inbox.jsonl"
        if inbox.exists():
            with open(inbox, "rb") as f:
                f.seek(self._offset)
                data = f.read()
            end = data.rfind(b"\n") + 1                                      # only complete lines
            self._offset += end
            for line in data[:end].decode("utf-8", "replace").splitlines():
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if m.get("id") not in self._emitted:
                    self._emit(m)
        return self

    def stop(self):
        self._write_heartbeat(False)


def main():
    import projects
    root = projects.resolve_project()
    w = Watcher(root, out=lambda s: print(s, flush=True))
    w.start()
    last_beat = time.time()
    try:
        while True:
            w.poll()
            if time.time() - last_beat >= 2:
                w.beat()
                last_beat = time.time()
            time.sleep(0.4)
    except KeyboardInterrupt:
        pass
    finally:
        w.stop()


if __name__ == "__main__":
    main()
