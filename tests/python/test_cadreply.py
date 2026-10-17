import json

import cadreply


def lines(root):
    return [json.loads(l) for l in (root / ".cad" / "chat.jsonl").read_text(encoding="utf-8").splitlines()]


def test_reply_goes_to_the_project_chat_tagged_with_the_model_of_the_last_question(project):
    (project / ".cad").mkdir()
    (project / ".cad" / "chat.jsonl").write_text(json.dumps({"id": "1", "role": "user", "text": "hi", "model": "table"}) + "\n", encoding="utf-8")
    cadreply.reply(project, "done")
    m = lines(project)[-1]
    assert m["role"] == "assistant" and m["text"] == "done" and m["model"] == "table"


def test_status_and_explicit_model(project):
    cadreply.reply(project, "working", status=True, model="shaft")
    m = lines(project)[-1]
    assert m["role"] == "status" and m["model"] == "shaft"


def test_reply_without_any_question_has_no_model(project):
    cadreply.reply(project, "hello")
    assert lines(project)[-1]["model"] is None
