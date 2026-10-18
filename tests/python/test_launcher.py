"""Desktop launcher (Ubuntu app icon) and the one-click start of the listening assistant."""
import os
import stat
import time

import pytest

import launcher


def test_desktop_entry_launches_the_app_and_offers_the_assistant_action(tmp_path):
    text = launcher.desktop_entry(tmp_path)
    assert text.startswith("[Desktop Entry]") and "Type=Application" in text and "Name=CAD chat" in text
    assert f"Exec={tmp_path}/cadchat app" in text and "Terminal=false" in text
    assert f"Icon={tmp_path}/assets/cadchat.svg" in text and "Categories=" in text
    assert "[Desktop Action Assistant]" in text and f"Exec={tmp_path}/cadchat assistant --terminal" in text


def test_paths_with_spaces_are_quoted_in_exec(tmp_path):
    d = tmp_path / "my apps" / "cadchat"
    d.mkdir(parents=True)
    text = launcher.desktop_entry(d)
    assert f'Exec="{d}/cadchat" app' in text


def test_install_writes_the_entry_and_uninstall_removes_it(tmp_path):
    apps = tmp_path / "applications"
    f = launcher.install(tmp_path / "app", apps_dir=apps)
    assert f == apps / "cadchat.desktop" and f.read_text(encoding="utf-8").startswith("[Desktop Entry]")
    assert f.stat().st_mode & stat.S_IXUSR                              # trusted launcher
    assert launcher.uninstall(apps_dir=apps) is True and not f.exists()
    assert launcher.uninstall(apps_dir=apps) is False


def test_the_assistant_command_starts_claude_code_in_the_app_with_the_project_in_the_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv("CADCHAT_ASSISTANT_CMD", raising=False)
    argv = launcher.assistant_argv(tmp_path / "proj")
    assert argv[0] == "claude" and str(tmp_path / "proj") in argv[-1] and "cad-viewer" in argv[-1]


def test_the_assistant_command_can_be_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("CADCHAT_ASSISTANT_CMD", "myagent --flag")
    assert launcher.assistant_argv(tmp_path)[:2] == ["myagent", "--flag"]


def test_terminal_prefix_can_be_set_and_wraps_the_command(monkeypatch):
    monkeypatch.setenv("CADCHAT_TERMINAL", "xterm -e")
    assert launcher.terminal_argv(["claude", "hi"]) == ["xterm", "-e", "claude", "hi"]


def test_without_any_terminal_the_command_runs_as_it_is(monkeypatch):
    monkeypatch.delenv("CADCHAT_TERMINAL", raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda n: None)
    assert launcher.terminal_argv(["claude"]) == ["claude"]


def test_start_assistant_spawns_once_within_a_short_time(project, tmp_path, monkeypatch):
    marker = tmp_path / "started"
    script = tmp_path / "fake_terminal.sh"
    script.write_text(f"#!/bin/sh\necho started >> {marker}\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("CADCHAT_TERMINAL", str(script))
    st = launcher.start_assistant(project, min_gap=60)
    assert st == "started"
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.05)
    assert marker.read_text(encoding="utf-8").count("started") == 1
    assert launcher.start_assistant(project, min_gap=60) == "already starting"


def test_cli_install_launcher_uses_the_data_home(tmp_path, monkeypatch, capsys):
    import cadchat
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert cadchat.main(["install-launcher"]) == 0
    assert (tmp_path / "data" / "applications" / "cadchat.desktop").exists()
    assert cadchat.main(["install-launcher", "--uninstall"]) == 0
    assert not (tmp_path / "data" / "applications" / "cadchat.desktop").exists()


# ---- clearing the chat resets the assistant session ---------------------------------------------------------------------------
@pytest.fixture
def fake_agent(tmp_path, monkeypatch):
    agent = tmp_path / "agent.sh"
    agent.write_text("#!/bin/sh\nsleep 60\n", encoding="utf-8")
    agent.chmod(0o755)
    monkeypatch.setenv("CADCHAT_ASSISTANT_CMD", str(agent))
    monkeypatch.delenv("CADCHAT_TERMINAL", raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda n: None)              # no terminal: the agent runs directly
    yield agent


def alive(pid):
    try:
        os.kill(pid, 0)
        return open(f"/proc/{pid}/stat").read().split()[2] != "Z"
    except (OSError, IndexError):
        return False


def wait_for(cond, tries=60):
    for _ in range(tries):
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_a_started_assistant_records_its_pid_and_can_be_stopped(project, fake_agent):
    assert launcher.start_assistant(project, min_gap=0) == "started"
    pidfile = project / ".cad" / "assistant.pid"
    assert wait_for(pidfile.exists)
    pid = int(pidfile.read_text(encoding="utf-8"))
    assert alive(pid)
    assert launcher.stop_assistant(project) == "stopped"
    assert wait_for(lambda: not alive(pid)) and not pidfile.exists()
    assert launcher.stop_assistant(project) == "not running"


def test_a_stale_pid_file_is_not_trusted(project, fake_agent):
    (project / ".cad").mkdir(exist_ok=True)
    (project / ".cad" / "assistant.pid").write_text(str(os.getpid()), encoding="utf-8")        # a live process that is not the assistant (this test)
    assert launcher.stop_assistant(project) == "not running"
    assert alive(os.getpid())


def test_restart_gives_a_fresh_session_only_when_one_was_started_by_the_viewer(project, fake_agent):
    assert launcher.restart_assistant(project) == "none"
    launcher.start_assistant(project, min_gap=0)
    pidfile = project / ".cad" / "assistant.pid"
    assert wait_for(pidfile.exists)
    old = int(pidfile.read_text(encoding="utf-8"))
    assert launcher.restart_assistant(project) == "restarted"
    assert wait_for(lambda: not alive(old))
    assert wait_for(lambda: pidfile.exists() and int(pidfile.read_text(encoding="utf-8")) != old)
    launcher.stop_assistant(project)


def test_stopping_also_ends_the_message_watch_the_assistant_left_behind(project, fake_agent):
    import json
    import subprocess
    watcher = subprocess.Popen(["sh", "-c", "sleep 60", "cadwatch"])                      # cmdline mentions cadwatch
    try:
        launcher.start_assistant(project, min_gap=0)
        assert wait_for((project / ".cad" / "assistant.pid").exists)
        (project / ".cad" / "assistant.json").write_text(json.dumps({"beat": time.time(), "pid": watcher.pid, "listening": True}), encoding="utf-8")
        assert launcher.stop_assistant(project) == "stopped"
        assert wait_for(lambda: watcher.poll() is not None)
    finally:
        if watcher.poll() is None:
            watcher.kill()
        watcher.wait()
