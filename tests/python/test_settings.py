"""User settings (agent command, terminal, projects folder, ...) kept in <CADCHAT_HOME>/settings.json."""
import json

import pytest

import settings


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CADCHAT_HOME", str(tmp_path / "cfg"))
    for v in ("CADCHAT_ASSISTANT_CMD", "CADCHAT_TERMINAL"):
        monkeypatch.delenv(v, raising=False)
    return tmp_path / "cfg"


def test_defaults_when_nothing_is_saved():
    s = settings.load()
    assert s["assistant_cmd"] == "claude" and s["terminal"] == "" and s["clearance"] == 0.2 and s["auto_open_chat"] is True


def test_save_merges_and_persists(home):
    settings.save({"assistant_cmd": "myagent --fast", "clearance": 0.15})
    s = settings.load()
    assert s["assistant_cmd"] == "myagent --fast" and s["clearance"] == 0.15 and s["auto_open_chat"] is True
    assert json.loads((home / "settings.json").read_text(encoding="utf-8"))["assistant_cmd"] == "myagent --fast"


def test_save_rejects_unknown_keys_and_bad_values():
    with pytest.raises(ValueError):
        settings.save({"nope": 1})
    with pytest.raises(ValueError):
        settings.save({"clearance": -1})
    with pytest.raises(ValueError):
        settings.save({"assistant_cmd": ""})
    with pytest.raises(ValueError):
        settings.save({"auto_open_chat": "yes"})
    assert settings.load()["clearance"] == 0.2


def test_a_damaged_file_falls_back_to_defaults(home):
    home.mkdir(parents=True)
    (home / "settings.json").write_text("{broken", encoding="utf-8")
    assert settings.load()["assistant_cmd"] == "claude"


def test_launcher_uses_the_saved_agent_and_terminal_unless_the_environment_overrides(tmp_path, monkeypatch):
    import launcher
    settings.save({"assistant_cmd": "myagent --x", "terminal": "xterm -e"})
    assert launcher.assistant_argv(tmp_path)[:2] == ["myagent", "--x"]
    assert launcher.terminal_argv(["a"]) == ["xterm", "-e", "a"]
    monkeypatch.setenv("CADCHAT_ASSISTANT_CMD", "other")
    monkeypatch.setenv("CADCHAT_TERMINAL", "konsole -e")
    assert launcher.assistant_argv(tmp_path)[0] == "other" and launcher.terminal_argv(["a"])[:2] == ["konsole", "-e"]


def test_projects_dir_is_expanded():
    settings.save({"projects_dir": "~/work/cad"})
    assert str(settings.projects_dir()).endswith("work/cad") and "~" not in str(settings.projects_dir())
