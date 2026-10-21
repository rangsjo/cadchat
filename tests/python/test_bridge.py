"""The per-message bridge: each chat message is run through the agent's non-interactive mode, its answer becomes the chat reply. The context
never grows because nothing is resent from earlier messages."""
import json
import stat
import threading
import time

import pytest

import bridge
import settings


def agent(tmp_path, body, name="agent.sh"):
    f = tmp_path / name
    f.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    f.chmod(f.stat().st_mode | stat.S_IXUSR)
    return f


def chat(project):
    p = project / ".cad" / "chat.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def msg(**kw):
    return {"id": "1", "role": "user", "text": "make the legs longer", "model": "table", "pose": {"fold_R": 90, "slide_R": 0, "gate_out_R": 45},
            "part": "leg", "parts": ["leg"], "point": [1, 2, 3], "normal": [0, 0, 1], "shot": ".cad/shots/1.png", **kw}


def test_the_prompt_carries_the_request_the_context_and_the_rules(project):
    p = bridge.build_prompt(project, msg())
    assert "make the legs longer" in p and "table" in p and str(project) in p
    assert "fold_R=90" in p and "slide_R" not in p                       # only joints that are not at zero
    assert str(project / ".cad" / "shots" / "1.png") in p                # the screenshot as an absolute path the agent can open
    assert "AGENTS.md" in p and "cadreply" in p and "do not" in p.lower()


def test_a_message_without_context_still_makes_a_prompt(project):
    p = bridge.build_prompt(project, {"id": "2", "role": "user", "text": "hi"})
    assert "hi" in p and "None" not in p


def test_the_agents_answer_becomes_the_reply_after_a_status_line(project, tmp_path):
    a = agent(tmp_path, 'echo "Lengthened the legs to 780 mm."')
    b = bridge.Bridge(project, provider="custom", command=str(a))
    b.handle(msg())
    roles = [m["role"] for m in chat(project)]
    assert roles == ["status", "assistant"]
    last = chat(project)[-1]
    assert last["text"] == "Lengthened the legs to 780 mm." and last["model"] == "table"


def test_the_agent_gets_the_prompt_as_its_last_argument_and_runs_in_the_app_folder(project, tmp_path):
    a = agent(tmp_path, 'pwd; echo "$1" | head -c 60')
    b = bridge.Bridge(project, provider="custom", command=str(a))
    b.handle(msg())
    text = chat(project)[-1]["text"]
    assert str(bridge.launcher.APP) in text and "You are the assistant" in text


def test_a_failing_agent_is_reported_not_swallowed(project, tmp_path):
    a = agent(tmp_path, 'echo "not logged in" >&2; exit 3')
    bridge.Bridge(project, provider="custom", command=str(a)).handle(msg())
    last = chat(project)[-1]
    assert last["role"] == "assistant" and "exit 3" in last["text"] and "not logged in" in last["text"]


def test_a_missing_agent_says_how_to_fix_it(project):
    b = bridge.Bridge(project, provider="custom", command="/no/such/agent-xyz")
    b.handle(msg())
    assert "could not start" in chat(project)[-1]["text"].lower()


def test_a_slow_agent_is_stopped_after_the_timeout(project, tmp_path):
    a = agent(tmp_path, "sleep 30")
    b = bridge.Bridge(project, provider="custom", command=str(a), timeout=0.6)
    t = time.time()
    b.handle(msg())
    assert time.time() - t < 10 and "timed out" in chat(project)[-1]["text"]


def test_long_answers_are_trimmed(project, tmp_path):
    a = agent(tmp_path, 'python3 -c "print(\'x\' * 20000)"')
    bridge.Bridge(project, provider="custom", command=str(a)).handle(msg())
    assert len(chat(project)[-1]["text"]) <= bridge.MAX_REPLY + 50


def test_the_loop_answers_new_messages_and_keeps_the_heartbeat(project, tmp_path):
    a = agent(tmp_path, 'echo "done: $(echo "$1" | head -c 5)"')
    b = bridge.Bridge(project, provider="custom", command=str(a))
    stop = threading.Event()
    th = threading.Thread(target=b.run, kwargs={"stop": stop, "poll": 0.1}, daemon=True)
    th.start()
    try:
        time.sleep(0.4)
        m = {"id": "9", "role": "user", "text": "hello there", "model": "t"}
        for name in ("chat.jsonl", "inbox.jsonl"):
            with open(project / ".cad" / name, "a", encoding="utf-8") as f:
                f.write(json.dumps(m) + "\n")
        for _ in range(100):
            if any(x["role"] == "assistant" for x in chat(project)):
                break
            time.sleep(0.1)
        assert any(x["role"] == "assistant" for x in chat(project))
        hb = json.loads((project / ".cad" / "assistant.json").read_text(encoding="utf-8"))
        assert hb["listening"] is True and time.time() - hb["beat"] < 5
    finally:
        stop.set()
        th.join(5)


def test_messages_that_were_not_answered_before_the_bridge_started_are_handled(project, tmp_path):
    (project / ".cad").mkdir(exist_ok=True)
    with open(project / ".cad" / "chat.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": "5", "role": "user", "text": "old question", "model": "t"}) + "\n")
    a = agent(tmp_path, 'echo "answered"')
    b = bridge.Bridge(project, provider="custom", command=str(a))
    stop = threading.Event()
    th = threading.Thread(target=b.run, kwargs={"stop": stop, "poll": 0.1}, daemon=True)
    th.start()
    try:
        for _ in range(100):
            if any(x["role"] == "assistant" for x in chat(project)):
                break
            time.sleep(0.1)
        assert chat(project)[-1]["text"] == "answered"
    finally:
        stop.set()
        th.join(5)


def test_system_notes_from_the_viewer_are_not_sent_to_the_agent(project, tmp_path):
    a = agent(tmp_path, 'echo "should not run"')
    b = bridge.Bridge(project, provider="custom", command=str(a))
    b.handle({"id": "6", "role": "system", "text": "The user cleared the chat"})
    assert chat(project) == []
