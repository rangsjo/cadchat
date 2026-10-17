"""start / stop / restart / status of the viewer server: the one-command way to (re)start it and keep working."""
import json
import socket
import time

import pytest

import cadchat


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def port(project):
    p = free_port()
    yield p
    cadchat.stop_server(project)


def test_status_when_nothing_runs(project, port):
    assert cadchat.server_status(project, port) is None


def test_start_launches_a_detached_server_and_reports_it(project, port):
    info = cadchat.start_server(project, port)
    assert info["port"] == port and info["pid"] > 0 and info["started"] is True
    st = cadchat.server_status(project, port)
    assert st["pid"] == info["pid"] and st["url"] == f"http://127.0.0.1:{port}/"
    assert cadchat.port_open(port)


def test_start_twice_reuses_the_running_server(project, port):
    first = cadchat.start_server(project, port)
    second = cadchat.start_server(project, port)
    assert second["pid"] == first["pid"] and second["started"] is False


def test_restart_gives_a_new_process_on_the_same_port_and_keeps_the_token(project, port):
    first = cadchat.start_server(project, port)
    token_before = (project / ".cad" / "token").read_text(encoding="utf-8")
    second = cadchat.restart_server(project, port)
    assert second["pid"] != first["pid"] and second["port"] == port and cadchat.port_open(port)
    assert (project / ".cad" / "token").read_text(encoding="utf-8") == token_before


def test_stop_frees_the_port_and_clears_the_pid_file(project, port):
    cadchat.start_server(project, port)
    assert cadchat.stop_server(project) is True
    deadline = time.time() + 5
    while cadchat.port_open(port) and time.time() < deadline:
        time.sleep(0.1)
    assert not cadchat.port_open(port) and cadchat.server_status(project, port) is None
    assert cadchat.stop_server(project) is False                 # nothing left to stop


def test_a_stale_pid_file_is_ignored(project, port):
    (project / ".cad").mkdir(exist_ok=True)
    (project / ".cad" / "server.json").write_text(json.dumps({"pid": 999999, "port": port}), encoding="utf-8")
    assert cadchat.server_status(project, port) is None
    assert cadchat.start_server(project, port)["started"] is True


def test_a_foreign_program_on_the_port_gives_a_clear_error(project, port):
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
        s.listen()
        with pytest.raises(RuntimeError, match="in use"):
            cadchat.start_server(project, port)


def test_a_server_that_cannot_start_reports_its_log(project, port, monkeypatch):
    monkeypatch.setattr(cadchat, "SERVER", project / "does_not_exist.py")
    with pytest.raises(RuntimeError, match="did not start"):
        cadchat.start_server(project, port, wait=3)


def test_cli_commands_roundtrip(project, port, capsys):
    assert cadchat.main(["status", "--port", str(port)], project) == 1
    assert cadchat.main(["start", "--port", str(port)], project) == 0
    assert cadchat.main(["status", "--port", str(port)], project) == 0
    assert "running" in capsys.readouterr().out
    assert cadchat.main(["restart", "--port", str(port)], project) == 0
    assert cadchat.main(["stop"], project) == 0


def test_a_second_project_gets_its_own_port_and_is_not_mistaken_for_the_first(tmp_path, monkeypatch):
    import projects
    monkeypatch.setenv("CADCHAT_HOME", str(tmp_path / "cfg"))
    a, b = projects.init_project(tmp_path / "a"), projects.init_project(tmp_path / "b")
    p = free_port()
    try:
        ia = cadchat.start_server(a, p)
        assert cadchat.server_status(b, p) is None                              # that port serves project a, not b
        ib = cadchat.start_server(b, None, default_port=p)
        assert ib["started"] and ib["port"] != p and ia["port"] == p
        assert cadchat.server_status(b, ib["port"])["port"] == ib["port"]
    finally:
        cadchat.stop_server(a)
        cadchat.stop_server(b)
