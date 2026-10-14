"""The Java bridge against a stub of PTC's J-Link classes: protocol, reflection calls, error reporting.
Real Creo is needed to prove the J-Link API names; these tests prove everything else."""
import json
import shutil
import subprocess
import sys

import pytest

from conftest import REPO

pytestmark = pytest.mark.skipif(not shutil.which("javac"), reason="needs a JDK")


@pytest.fixture(scope="module")
def classes(tmp_path_factory):
    out = tmp_path_factory.mktemp("jclasses")
    sources = [str(p) for p in (REPO / "tests" / "creo" / "stubs").rglob("*.java")] + [str(REPO / "creo" / "bridge" / "CreoBridge.java")]
    r = subprocess.run(["javac", "-d", str(out), *sources], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


@pytest.fixture
def step_file(tmp_path):
    from build123d import Box
    import exchange
    return exchange.export_step_assembly([("bracket", Box(10, 20, 30))], tmp_path / "src.step", name="bracket")


class Bridge:
    def __init__(self, classes, step, *props):
        cmd = ["java", "-Dcreo.skipLoadLibrary=true", f"-Dfake.step={step}", *props, "-cp", str(classes), "CreoBridge"]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.n = 0

    def ask(self, cmd, **args):
        self.n += 1
        self.p.stdin.write(json.dumps({"id": self.n, "cmd": cmd, **args}) + "\n")
        self.p.stdin.flush()
        reply = json.loads(self.p.stdout.readline())
        assert reply["id"] == self.n
        return reply

    def close(self):
        try:
            self.ask("quit")
        except Exception:
            pass
        self.p.kill()


@pytest.fixture
def bridge(classes, step_file):
    b = Bridge(classes, step_file)
    yield b
    b.close()


def test_ping_and_unknown_command(bridge):
    assert bridge.ask("ping")["ok"] is True
    r = bridge.ask("frobnicate")
    assert r["ok"] is False and "unknown command" in r["error"]


def test_status_before_connect_says_not_connected(bridge):
    r = bridge.ask("status")
    assert r["ok"] and r["connected"] is False


def test_connect_then_status_reports_model_and_fingerprint(bridge):
    assert bridge.ask("connect")["ok"]
    r = bridge.ask("status")
    assert r["connected"] is True and r["model"] == "bracket.prt" and r["fingerprint"]


def test_connect_to_a_missing_creo_gives_a_readable_error(classes, step_file):
    b = Bridge(classes, step_file, "-Dfake.creo.running=false")
    try:
        r = b.ask("connect")
        assert r["ok"] is False and "no Creo Parametric process" in r["error"]
    finally:
        b.close()


def test_connect_can_start_creo(classes, step_file):
    b = Bridge(classes, step_file)
    try:
        assert b.ask("connect", start='"C:\\Program Files\\PTC\\parametric.exe" -g:no_graphics')["ok"]
    finally:
        b.close()


def test_status_without_a_model(classes, step_file):
    b = Bridge(classes, step_file, "-Dfake.nomodel=true")
    try:
        b.ask("connect")
        r = b.ask("status")
        assert r["connected"] is True and r["model"] is None
    finally:
        b.close()


def test_params_lists_user_parameters_and_dimensions_with_types(bridge):
    bridge.ask("connect")
    ps = {p["name"]: p for p in bridge.ask("params")["params"]}
    assert ps["LENGTH"]["value"] == 60.0 and ps["LENGTH"]["kind"] == "param" and ps["LENGTH"]["type"] == "double"
    assert ps["NOTE"]["value"] == "hello" and ps["NOTE"]["type"] == "string"
    assert ps["d1"]["value"] == 10.5 and ps["d1"]["kind"] == "dimension"


def test_set_changes_a_parameter_and_the_fingerprint(bridge):
    bridge.ask("connect")
    before = bridge.ask("status")["fingerprint"]
    assert bridge.ask("set", name="LENGTH", value=75.5)["ok"]
    assert {p["name"]: p["value"] for p in bridge.ask("params")["params"]}["LENGTH"] == 75.5
    assert bridge.ask("status")["fingerprint"] != before


def test_set_changes_a_dimension(bridge):
    bridge.ask("connect")
    assert bridge.ask("set", name="d1", value=22.0)["ok"]
    assert {p["name"]: p["value"] for p in bridge.ask("params")["params"]}["d1"] == 22.0


def test_set_text_parameter(bridge):
    bridge.ask("connect")
    assert bridge.ask("set", name="NOTE", value="world")["ok"]
    assert {p["name"]: p["value"] for p in bridge.ask("params")["params"]}["NOTE"] == "world"


def test_set_unknown_name_is_an_error(bridge):
    bridge.ask("connect")
    r = bridge.ask("set", name="NOPE", value=1)
    assert r["ok"] is False and "NOPE" in r["error"]


def test_regenerate_succeeds(bridge):
    bridge.ask("connect")
    assert bridge.ask("regenerate")["ok"]


def test_export_step_writes_the_file(bridge, tmp_path):
    bridge.ask("connect")
    out = tmp_path / "out.step"
    r = bridge.ask("export_step", path=str(out))
    assert r["ok"] and out.exists() and out.stat().st_size > 100


def test_commands_before_connect_are_a_clean_error(bridge):
    r = bridge.ask("params")
    assert r["ok"] is False and "not connected" in r["error"]


def test_bad_json_does_not_kill_the_bridge(bridge):
    bridge.p.stdin.write("this is not json\n")
    bridge.p.stdin.flush()
    reply = json.loads(bridge.p.stdout.readline())
    assert reply["ok"] is False
    assert bridge.ask("ping")["ok"]
