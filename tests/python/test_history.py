"""Version history per model: every publish keeps a snapshot of the script and its parameters (deduplicated), together with what the
user had last asked for, so a project can be taken back to an earlier state."""
import json
import time

import pytest

import history


@pytest.fixture
def proj(project):
    (project / ".cad").mkdir(exist_ok=True)
    return project


def write_script(proj, text):
    (proj / "parts" / "m.py").write_text(text, encoding="utf-8")


def ask(proj, text, model="m", mid="1"):
    with open(proj / ".cad" / "chat.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": mid, "role": "user", "text": text, "model": model}) + "\n")


def test_snapshot_keeps_script_and_params_and_the_last_request(proj):
    write_script(proj, "v = 1\n")
    ask(proj, "make it taller")
    (proj / ".cad" / "models" / "m").mkdir(parents=True)
    (proj / ".cad" / "models" / "m" / "params.json").write_text('{"h": 5}', encoding="utf-8")
    sid = history.snapshot(proj, "m", "parts/m.py")
    items = history.list_history(proj, "m")
    assert [i["id"] for i in items] == [sid] and items[0]["note"] == "make it taller"
    assert history.read(proj, "m", sid) == {"script": "v = 1\n", "params": {"h": 5}}


def test_identical_state_is_not_snapshotted_twice(proj):
    write_script(proj, "v = 1\n")
    assert history.snapshot(proj, "m", "parts/m.py") is not None
    assert history.snapshot(proj, "m", "parts/m.py") is None


def test_changes_make_new_snapshots_newest_first(proj):
    write_script(proj, "v = 1\n")
    a = history.snapshot(proj, "m", "parts/m.py")
    time.sleep(0.01)
    write_script(proj, "v = 2\n")
    b = history.snapshot(proj, "m", "parts/m.py")
    assert [i["id"] for i in history.list_history(proj, "m")] == [b, a]


def test_only_the_last_snapshots_are_kept(proj):
    for i in range(history.KEEP + 5):
        write_script(proj, f"v = {i}\n")
        history.snapshot(proj, "m", "parts/m.py")
    assert len(history.list_history(proj, "m")) == history.KEEP


def test_restore_writes_script_and_params_back_after_saving_the_current_state(proj):
    write_script(proj, "v = 1\n")
    old = history.snapshot(proj, "m", "parts/m.py")
    write_script(proj, "v = 2  # unsaved edit\n")
    history.restore(proj, "m", old, "parts/m.py")
    assert (proj / "parts" / "m.py").read_text(encoding="utf-8") == "v = 1\n"
    assert any(history.read(proj, "m", i["id"])["script"].startswith("v = 2") for i in history.list_history(proj, "m"))      # nothing is lost


def test_unknown_snapshots_and_models_are_errors(proj):
    with pytest.raises(KeyError):
        history.read(proj, "m", "nope")
    with pytest.raises(ValueError):
        history.list_history(proj, "../x")
