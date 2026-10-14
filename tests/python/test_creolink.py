"""Creo link logic: discovery, environment, the bridge protocol and the sync loop, all without Creo."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

import creolink

FAKE = Path(__file__).with_name("fake_bridge.py")


def make_creo(base, version="10.0.5.0", jar=True, dll=True, comm=True):
    load = base / "PTC" / f"Creo {version}"
    (load / "Parametric" / "bin").mkdir(parents=True)
    (load / "Parametric" / "bin" / "parametric.exe").write_text("")
    cf = load / "Common Files"
    (cf / "text" / "java").mkdir(parents=True)
    (cf / "x86e_win64" / "lib").mkdir(parents=True)
    (cf / "x86e_win64" / "obj").mkdir(parents=True)
    if jar:
        (cf / "text" / "java" / "pfcasync.jar").write_text("")
    if dll:
        (cf / "x86e_win64" / "lib" / "pfcasyncmt.dll").write_text("")
    if comm:
        (cf / "x86e_win64" / "obj" / "pro_comm_msg.exe").write_text("")
    return load


# ---- discovery -----------------------------------------------------------------------------------------------------
def test_discover_picks_the_newest_creo(tmp_path):
    make_creo(tmp_path, "9.0.2.0")
    newest = make_creo(tmp_path, "11.0.0.0")
    make_creo(tmp_path, "10.0.5.0")
    c = creolink.discover_creo([tmp_path / "PTC"])
    assert c.load == newest and c.version == (11, 0, 0, 0)
    assert c.parametric.name == "parametric.exe" and c.jar.name == "pfcasync.jar"
    assert c.dll_dir.name == "lib" and c.comm_msg.name == "pro_comm_msg.exe" and c.problems == []


def test_discover_returns_none_when_creo_is_not_installed(tmp_path):
    assert creolink.discover_creo([tmp_path]) is None


def test_discover_lists_what_is_missing(tmp_path):
    make_creo(tmp_path, jar=False, comm=False)
    c = creolink.discover_creo([tmp_path / "PTC"])
    assert any("pfcasync.jar" in p for p in c.problems) and any("pro_comm_msg" in p for p in c.problems)


def test_discover_honours_creo_home(tmp_path, monkeypatch):
    load = make_creo(tmp_path / "custom")
    monkeypatch.setenv("CREO_HOME", str(load))
    assert creolink.discover_creo([tmp_path / "nowhere"]).load == load


def test_build_env_wires_up_the_j_link_requirements(tmp_path):
    c = creolink.discover_creo([make_creo(tmp_path).parent])
    env = creolink.build_env(c, {"PATH": "C:\\Windows", "KEEP": "1"})
    assert env["PRO_COMM_MSG_EXE"] == str(c.comm_msg)
    assert env["PATH"].split(os.pathsep)[0] == str(c.dll_dir) and "C:\\Windows" in env["PATH"]
    assert str(c.jar) in env["CLASSPATH"] and env["KEEP"] == "1"


def test_discover_java_prefers_java_home(tmp_path, monkeypatch):
    home = tmp_path / "jdk"
    (home / "bin").mkdir(parents=True)
    for n in ("java", "javac"):
        (home / "bin" / n).write_text("")
    monkeypatch.setenv("JAVA_HOME", str(home))
    j = creolink.discover_java()
    assert j.javac == home / "bin" / "javac" and j.java == home / "bin" / "java"


def test_discover_java_without_a_jdk_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "none"))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert creolink.discover_java() is None


# ---- doctor --------------------------------------------------------------------------------------------------------
def test_doctor_names_each_failed_check_with_a_hint(tmp_path, monkeypatch):
    make_creo(tmp_path, jar=False)
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "none"))
    monkeypatch.setenv("PATH", str(tmp_path))
    checks = {name: (ok, detail) for name, ok, detail in creolink.doctor([tmp_path / "PTC"], port=1)}
    assert checks["Creo Parametric installed"][0] is True
    assert checks["pfcasync.jar (J-Link)"][0] is False and "pfcasync.jar" in checks["pfcasync.jar (J-Link)"][1]
    assert checks["JDK 11+ (javac)"][0] is False and "Temurin" in checks["JDK 11+ (javac)"][1]


def test_doctor_without_creo(tmp_path):
    checks = {name: ok for name, ok, _ in creolink.doctor([tmp_path], port=1)}
    assert checks["Creo Parametric installed"] is False


# ---- bridge process ------------------------------------------------------------------------------------------------
@pytest.fixture
def fake_state(tmp_path):
    p = tmp_path / "fake_state.json"
    from build123d import Box
    import exchange
    step = exchange.export_step_assembly([("bracket", Box(10, 20, 30))], tmp_path / "creo_out.step", name="bracket")
    p.write_text(json.dumps({"connected": False, "model": "bracket.prt", "fp": "1",
                             "params": [{"name": "LENGTH", "value": 60.0, "kind": "param", "type": "double"}],
                             "step_src": str(step)}))
    return p


def read_state(p):
    return json.loads(p.read_text())


@pytest.fixture
def bridge(fake_state):
    b = creolink.Bridge([sys.executable, str(FAKE)], env={**os.environ, "FAKE_CREO_STATE": str(fake_state)})
    yield b
    b.close()


def test_bridge_request_roundtrip(bridge):
    assert bridge.request("status")["connected"] is False
    assert bridge.request("connect")["ok"] is True
    assert bridge.request("status")["connected"] is True


def test_bridge_error_replies_raise_with_the_message(bridge, fake_state):
    s = read_state(fake_state); s["creo_running"] = False; fake_state.write_text(json.dumps(s))
    with pytest.raises(creolink.BridgeError, match="no Creo Parametric process"):
        bridge.request("connect")


def test_bridge_timeout_kills_the_process(fake_state):
    b = creolink.Bridge([sys.executable, str(FAKE)], env={**os.environ, "FAKE_CREO_STATE": str(fake_state)})
    with pytest.raises(creolink.BridgeTimeout):
        b.request("hang", timeout=0.5)
    assert b.proc.poll() is not None
    b.close()


def test_bridge_restarts_after_a_crash(bridge):
    bridge.request("status")
    bridge.proc.kill()
    bridge.proc.wait()
    assert bridge.request("status")["ok"] is True


# ---- the sync loop -------------------------------------------------------------------------------------------------
class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, path, name):
        assert Path(path).exists() and Path(path).stat().st_size > 100
        self.calls.append((Path(path).name, name))
        return name


@pytest.fixture
def link(project, bridge, fake_state):
    s = read_state(fake_state); s["connected"] = True; fake_state.write_text(json.dumps(s))
    rec = Recorder()
    l = creolink.CreoLink(project, bridge, importer=rec, clock=lambda: 1000.0)
    l.rec, l.fake = rec, fake_state
    return l


def state_of(project):
    return json.loads((project / ".cad" / "creo" / "state.json").read_text())


def test_first_step_exports_and_imports_the_current_model(link, project):
    link.step()
    assert link.rec.calls == [("bracket.step", "creo_bracket")]
    st = state_of(project)
    assert st["connected"] is True and st["model"] == "bracket.prt" and st["model_id"] == "creo_bracket"
    assert st["params"][0]["name"] == "LENGTH" and st["last_sync"] == 1000.0 and st["updated"] == 1000.0


def test_unchanged_model_is_not_exported_again(link):
    link.step(); link.step(); link.step()
    assert len(link.rec.calls) == 1


def test_changed_geometry_fingerprint_triggers_a_new_import(link):
    link.step()
    s = read_state(link.fake); s["fp"] = "2"; link.fake.write_text(json.dumps(s))
    link.step()
    assert len(link.rec.calls) == 2


def test_switching_to_another_model_imports_it_under_its_own_id(link):
    link.step()
    s = read_state(link.fake); s["model"] = "My Part.asm.3"; link.fake.write_text(json.dumps(s))
    link.step()
    assert link.rec.calls[-1][1] == "creo_My_Part"


def test_auto_sync_off_only_updates_the_status(link, project):
    link.auto_sync = False
    link.step()
    assert link.rec.calls == [] and state_of(project)["auto_sync"] is False and state_of(project)["model"] == "bracket.prt"


def test_not_connected_tries_to_connect_and_reports_when_creo_is_missing(project, bridge, fake_state):
    s = read_state(fake_state); s["creo_running"] = False; fake_state.write_text(json.dumps(s))
    rec = Recorder()
    l = creolink.CreoLink(project, bridge, importer=rec, clock=lambda: 5.0)
    l.step()
    st = state_of(project)
    assert st["connected"] is False and "no Creo Parametric process" in st["last_error"] and rec.calls == []


def send(project, **cmd):
    d = project / ".cad" / "creo"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "commands.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(cmd) + "\n")


def test_set_command_changes_creo_regenerates_and_re_imports(link, project):
    link.step()
    send(project, id="c1", cmd="set", name="LENGTH", value=75.0)
    link.step()
    log = [c["cmd"] for c in read_state(link.fake)["log"]]
    assert log.index("set") < log.index("regenerate") < len(log) - log[::-1].index("export_step") - 1
    assert len(link.rec.calls) == 2
    st = state_of(project)
    assert st["last_result"]["id"] == "c1" and st["last_result"]["ok"] is True
    assert {p["name"]: p["value"] for p in st["params"]}["LENGTH"] == 75.0


def test_commands_are_processed_once(link, project):
    link.step()
    send(project, id="c1", cmd="sync")
    link.step(); link.step()
    assert len(link.rec.calls) == 2


def test_failed_set_is_reported_and_the_loop_survives(link, project):
    link.step()
    send(project, id="c2", cmd="set", name="NOPE", value=1)
    link.step()
    r = state_of(project)["last_result"]
    assert r["ok"] is False and "NOPE" in r["message"]
    link.step()


def test_unknown_command_is_rejected(link, project):
    send(project, id="c3", cmd="format_disk")
    link.step()
    assert state_of(project)["last_result"]["ok"] is False


def test_auto_sync_command_toggles(link, project):
    send(project, id="c4", cmd="auto_sync", value=False)
    link.step()
    assert link.auto_sync is False and state_of(project)["auto_sync"] is False


def test_export_failure_is_recorded_and_retried_next_time(link, project):
    s = read_state(link.fake); s["fail"] = {"export_step": "XToolkitGeneralError: busy"}; link.fake.write_text(json.dumps(s))
    link.step()
    assert "busy" in state_of(project)["last_error"] and link.rec.calls == []
    s = read_state(link.fake); s["fail"] = {}; link.fake.write_text(json.dumps(s))
    link.step()
    assert len(link.rec.calls) == 1 and state_of(project)["last_error"] == ""
