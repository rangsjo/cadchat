"""LineProcess: a child process that answers one JSON line per request. Must work on Windows too, so no select() on pipes."""
import json
import sys

import pytest

from lineproc import LineProcess, ProcessError, ProcessTimeout

ECHO = r'''
import json, sys, time
for line in sys.stdin:
    r = json.loads(line)
    if r.get("sleep"):
        time.sleep(r["sleep"])
    if r.get("crash"):
        sys.exit(3)
    if r.get("noise"):
        print("not json at all", flush=True)
    print(json.dumps({"id": r["id"], "ok": True, "echo": r, "pid": __import__("os").getpid()}), flush=True)
'''


def echo():
    return LineProcess([sys.executable, "-c", ECHO])


def test_request_roundtrip_adds_and_matches_the_id():
    p = echo()
    try:
        r1, r2 = p.request({"a": 1}), p.request({"a": 2})
        assert r1["echo"]["a"] == 1 and r2["echo"]["a"] == 2 and r1["id"] != r2["id"]
    finally:
        p.stop()


def test_process_is_started_lazily_and_reused():
    p = echo()
    assert p.pid is None
    pid = p.request({"x": 1})["pid"]
    assert p.pid == pid and p.request({"x": 2})["pid"] == pid
    p.stop()


def test_timeout_kills_the_process_and_the_next_request_restarts_it():
    p = echo()
    first = p.request({"x": 1})["pid"]
    with pytest.raises(ProcessTimeout):
        p.request({"sleep": 5}, timeout=0.4)
    assert p.pid is None
    assert p.request({"x": 2})["pid"] != first
    p.stop()


def test_crash_is_reported_then_recovers():
    p = echo()
    p.request({"x": 1})
    with pytest.raises(ProcessError, match="exited"):
        p.request({"crash": True})
    assert p.request({"x": 2})["ok"] is True
    p.stop()


def test_non_json_output_is_skipped():
    p = echo()
    assert p.request({"noise": True})["ok"] is True
    p.stop()


def test_large_and_unicode_payloads():
    p = echo()
    big = "å" * 200_000
    assert p.request({"s": big})["echo"]["s"] == big
    p.stop()


def test_stderr_goes_to_the_log_file(tmp_path):
    log = tmp_path / "err.log"
    p = LineProcess([sys.executable, "-c", "import sys; sys.stderr.write('oops\\n'); sys.stderr.flush(); print('{\"id\":1,\"ok\":true}', flush=True); sys.stdin.readline()"], log=log)
    p.request({"id": 1})
    p.stop()
    assert "oops" in log.read_text(encoding="utf-8")


def test_stop_is_idempotent():
    p = echo()
    p.stop()
    p.request({"x": 1})
    p.stop()
    p.stop()
