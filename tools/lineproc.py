"""A child process that answers one JSON line per request (cadworker, the Creo bridge).

Reads replies on a thread and waits on a queue, because select() does not work on pipes on Windows.
"""
import itertools
import json
import queue
import subprocess
import threading


class ProcessError(Exception):
    pass


class ProcessTimeout(ProcessError):
    pass


class LineProcess:
    def __init__(self, cmd, env=None, cwd=None, log=None):
        self.cmd, self.env, self.cwd, self.log = list(cmd), env, cwd, log
        self.proc, self.last_proc, self.q, self._ids = None, None, None, itertools.count(1)
        self._logfile = None

    @property
    def pid(self):
        return self.proc.pid if self.proc and self.proc.poll() is None else None

    def start(self):
        self.stop()
        self._logfile = open(self.log, "ab") if self.log else subprocess.DEVNULL
        self.proc = subprocess.Popen(self.cmd, env=self.env, cwd=self.cwd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self._logfile)
        self.last_proc = self.proc
        self.q = queue.Queue()
        threading.Thread(target=self._read, args=(self.proc, self.q), daemon=True).start()

    @staticmethod
    def _read(proc, q):
        for line in iter(proc.stdout.readline, b""):
            q.put(line)
        q.put(None)

    def stop(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.kill()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            for s in (self.proc.stdin, self.proc.stdout):
                try:
                    s.close()
                except OSError:
                    pass
        if self._logfile not in (None, subprocess.DEVNULL):
            self._logfile.close()
        self.proc, self.q, self._logfile = None, None, None

    def request(self, obj, timeout=30.0):
        if self.proc is None or self.proc.poll() is not None:
            self.start()
        rid = obj.get("id") or next(self._ids)
        data = (json.dumps({**obj, "id": rid}) + "\n").encode("utf-8")
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except OSError:
            self.stop()
            raise ProcessError("process exited before the request could be sent")
        import time
        end = time.monotonic() + timeout
        while True:
            try:
                line = self.q.get(timeout=max(0.0, end - time.monotonic()))
            except queue.Empty:
                self.stop()
                raise ProcessTimeout(f"no reply within {timeout:g} s; the process was stopped")
            if line is None:
                self.stop()
                raise ProcessError("process exited")
            try:
                reply = json.loads(line.decode("utf-8"))
            except ValueError:
                continue                                    # stray output from a library: ignore
            if reply.get("id") == rid:
                return reply
