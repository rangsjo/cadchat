"""Whole chain without Creo: viewer API -> command file -> CreoLink -> Java bridge (stub J-Link) -> STEP -> imported model."""
import http.client
import json
import shutil
import subprocess
import threading

import pytest

import cadserver
import creolink

from conftest import REPO

pytestmark = pytest.mark.skipif(not shutil.which("javac"), reason="needs a JDK")


@pytest.fixture
def chain(project, tmp_path):
    out = tmp_path / "classes"
    sources = [str(p) for p in (REPO / "tests" / "creo" / "stubs").rglob("*.java")] + [str(REPO / "creo" / "bridge" / "CreoBridge.java")]
    assert subprocess.run(["javac", "-d", str(out), *sources], capture_output=True).returncode == 0
    from build123d import Box
    import exchange
    step = exchange.export_step_assembly([("bracket", Box(10, 20, 30))], tmp_path / "creo_out.step", name="bracket")
    bridge = creolink.Bridge(["java", "-Dcreo.skipLoadLibrary=true", f"-Dfake.step={step}", "-cp", str(out), "CreoBridge"], timeout=30)
    link = creolink.CreoLink(project, bridge, poll=0)
    httpd, token = cadserver.make_server(project, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def api(method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Host": f"127.0.0.1:{port}", "X-CAD-Token": token, "Content-Type": "application/json"})
        return json.loads(c.getresponse().read())

    yield link, api
    bridge.close()
    httpd.shutdown()


def test_creo_model_appears_in_the_viewer_with_its_parameters(chain):
    link, api = chain
    link.step()
    models = api("GET", "/api/models")
    assert "creo_bracket" in [m["id"] for m in models["models"]] and models["latest"] == "creo_bracket"
    creo = api("GET", "/api/creo")
    assert creo["running"] and creo["connected"] and creo["model"] == "bracket.prt"
    assert {p["name"] for p in creo["params"]} == {"LENGTH", "WIDTH", "NOTE", "d1"}
    parts = api("GET", "/api/model?m=creo_bracket")["parts"]
    assert [p["name"] for p in parts] == ["bracket"] and parts[0]["volume"] == pytest.approx(6000, abs=1)


def test_editing_a_parameter_in_the_viewer_reaches_creo_and_comes_back(chain):
    link, api = chain
    link.step()
    first = {m["id"]: m["mtime"] for m in api("GET", "/api/models")["models"]}["creo_bracket"]
    cmd = api("POST", "/api/creo/command", {"cmd": "set", "name": "LENGTH", "value": 88.0})
    import time
    time.sleep(0.05)
    link.step()
    creo = api("GET", "/api/creo")
    assert creo["last_result"]["id"] == cmd["id"] and creo["last_result"]["ok"] is True
    assert {p["name"]: p["value"] for p in creo["params"]}["LENGTH"] == 88.0
    assert {m["id"]: m["mtime"] for m in api("GET", "/api/models")["models"]}["creo_bracket"] > first      # re-imported


def test_unknown_parameter_comes_back_as_a_readable_failure(chain):
    link, api = chain
    link.step()
    api("POST", "/api/creo/command", {"cmd": "set", "name": "NOPE", "value": 1})
    link.step()
    r = api("GET", "/api/creo")["last_result"]
    assert r["ok"] is False and "NOPE" in r["message"]
