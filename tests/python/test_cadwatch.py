"""cadwatch: the process the assistant's Monitor runs. It forwards new viewer messages, replays the ones nobody answered
(for example after the watch expired) and publishes a heartbeat so the viewer can show whether anyone is listening."""
import json

import cadwatch


def write_lines(path, *objs):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o) + "\n")


def user(i, text="hi", **kw):
    return {"id": i, "role": "user", "text": text, **kw}


def reply(i, role="assistant"):
    return {"id": i, "role": role, "text": "ok"}


# ---- which messages are still open ------------------------------------------------------------------------------------------
def test_unanswered_means_no_assistant_reply_after_the_message():
    chat = [user("a", "one"), reply("r1"), user("b", "two"), user("c", "three")]
    assert [m["id"] for m in cadwatch.unanswered(chat)] == ["b", "c"]


def test_a_status_line_alone_does_not_answer_a_message():
    assert [m["id"] for m in cadwatch.unanswered([user("a"), reply("s", "status")])] == ["a"]


def test_identical_repeats_are_collapsed_into_the_latest_with_a_count():
    chat = [user("a", "make it taller", part="leg"), user("b", "make it taller", part="leg"), user("c", "other")]
    out = cadwatch.unanswered(chat)
    assert [m["id"] for m in out] == ["b", "c"] and out[0]["repeats"] == 2 and "repeats" not in out[1]


def test_no_messages_no_backlog():
    assert cadwatch.unanswered([]) == []


# ---- the watcher ----------------------------------------------------------------------------------------------------------
def make(project, clock=lambda: 100.0):
    out = []
    return cadwatch.Watcher(project, out=out.append, clock=clock), out


def test_start_replays_the_backlog_and_marks_it_seen(project):
    write_lines(project / ".cad" / "chat.jsonl", user("a"), reply("r1"), user("b", "old"), user("c", "newer"))
    w, out = make(project)
    w.start()
    assert [json.loads(l)["id"] for l in out] == ["b", "c"]
    seen = [json.loads(l)["id"] for l in (project / ".cad" / "seen.jsonl").read_text(encoding="utf-8").splitlines()]
    assert seen == ["b", "c"]
    assert all(json.loads(l)["backlog"] is True for l in out)


def test_new_inbox_lines_are_forwarded_once(project):
    w, out = make(project)
    w.start()
    write_lines(project / ".cad" / "inbox.jsonl", user("n1", "first"))
    w.poll(); w.poll()
    assert [json.loads(l)["id"] for l in out] == ["n1"]
    write_lines(project / ".cad" / "inbox.jsonl", user("n2", "second"))
    w.poll()
    assert [json.loads(l)["id"] for l in out] == ["n1", "n2"]


def test_a_message_already_replayed_as_backlog_is_not_sent_again(project):
    write_lines(project / ".cad" / "chat.jsonl", user("b"))
    write_lines(project / ".cad" / "inbox.jsonl", user("b"))
    w, out = make(project)
    w.start()
    w.poll()
    assert [json.loads(l)["id"] for l in out] == ["b"]


def test_heartbeat_file_shows_when_the_assistant_was_last_listening(project):
    t = [100.0]
    w, _ = make(project, clock=lambda: t[0])
    w.start()
    hb = json.loads((project / ".cad" / "assistant.json").read_text(encoding="utf-8"))
    assert hb["beat"] == 100.0 and hb["since"] == 100.0 and hb["pid"] > 0
    t[0] = 130.0
    w.beat()
    hb = json.loads((project / ".cad" / "assistant.json").read_text(encoding="utf-8"))
    assert hb["beat"] == 130.0 and hb["since"] == 100.0


def test_stopping_marks_the_assistant_as_gone(project):
    w, _ = make(project)
    w.start()
    w.stop()
    assert json.loads((project / ".cad" / "assistant.json").read_text(encoding="utf-8"))["listening"] is False


def test_damaged_lines_are_skipped(project):
    (project / ".cad").mkdir(exist_ok=True)
    (project / ".cad" / "inbox.jsonl").write_text("not json\n", encoding="utf-8")
    w, out = make(project)
    w.start()
    write_lines(project / ".cad" / "inbox.jsonl", user("ok"))
    w.poll()
    assert [json.loads(l)["id"] for l in out] == ["ok"]
