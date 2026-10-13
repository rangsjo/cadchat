import http.client
import json
import re
import threading
import time

import pytest

import cadserver


@pytest.fixture
def server(project):
    httpd, token = cadserver.make_server(project, port=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    class S:
        pass

    s = S()
    s.port, s.token, s.root = port, token, project

    def call(method, path, body=None, token=token, host=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        headers = {"Host": host or f"127.0.0.1:{port}"}
        if token:
            headers["X-CAD-Token"] = token
        data = json.dumps(body) if body is not None else None
        if data:
            headers["Content-Type"] = "application/json"
        c.request(method, path, data, headers)
        r = c.getresponse()
        raw = r.read().decode()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw

    s.call = call
    yield s
    httpd.shutdown()


def build(server, write_script, name, kind="static"):
    write_script(name, kind)
    status, r = server.call("POST", "/api/build", {"script": name})
    assert status == 200 and r["ok"], r


# ---- access control --------------------------------------------------------------------------------------------
def test_page_embeds_a_token_and_serves_the_app(server):
    status, html = server.call("GET", "/", token=None)
    assert status == 200 and re.search(r'CAD_TOKEN="[\w-]{10,}"', html)


def test_foreign_host_header_is_rejected(server):
    assert server.call("GET", "/api/models", host="evil.example:80")[0] == 403


def test_post_needs_the_token(server):
    assert server.call("POST", "/api/check", {"m": "x", "values": {}}, token=None)[0] == 403
    assert server.call("POST", "/api/check", {"m": "x", "values": {}}, token="wrong")[0] == 403


def test_static_files_cannot_escape_the_static_dir(server):
    assert server.call("GET", "/../cadserver.py", token=None)[0] == 404
    assert server.call("GET", "/%2e%2e/cadserver.py", token=None)[0] == 404


# ---- model listing -------------------------------------------------------------------------------------------------
def test_empty_project_lists_no_models(server):
    status, r = server.call("GET", "/api/models")
    assert status == 200 and r == {"models": [], "latest": None}


def test_unbuilt_scripts_are_listed_and_can_be_built(server, write_script):
    write_script("plate")
    (server.root / "parts" / "_private.py").write_text("x = 1")
    r = server.call("GET", "/api/models")[1]
    assert [(m["id"], m["built"]) for m in r["models"]] == [("plate", False)]
    build(server, write_script, "plate")
    r = server.call("GET", "/api/models")[1]
    assert [(m["id"], m["built"], m["parts"]) for m in r["models"]] == [("plate", True, 1)]
    assert r["latest"] == "plate"


def test_latest_is_the_most_recently_published_model(server, write_script):
    build(server, write_script, "a")
    time.sleep(0.05)
    build(server, write_script, "b")
    assert server.call("GET", "/api/models")[1]["latest"] == "b"
    time.sleep(0.05)
    server.call("POST", "/api/build", {"script": "a"})
    assert server.call("GET", "/api/models")[1]["latest"] == "a"


def test_get_model_returns_the_published_json(server, write_script):
    build(server, write_script, "blk")
    status, m = server.call("GET", "/api/model?m=blk")
    assert status == 200 and m["name"] == "blk" and m["parts"][0]["name"] == "block"


def test_model_ids_cannot_traverse_directories(server):
    assert server.call("GET", "/api/model?m=../../etc")[0] == 400
    assert server.call("GET", "/api/model?m=nope")[0] == 404


def test_version_reports_a_stamp_per_model(server, write_script):
    build(server, write_script, "a")
    v1 = server.call("GET", "/api/version")[1]["models"]["a"]
    time.sleep(0.05)
    server.call("POST", "/api/build", {"script": "a"})
    assert server.call("GET", "/api/version")[1]["models"]["a"] != v1


def test_build_only_accepts_scripts_from_parts(server):
    assert server.call("POST", "/api/build", {"script": "../evil"})[0] == 400
    assert server.call("POST", "/api/build", {"script": "missing"})[0] == 404


# ---- collision check -----------------------------------------------------------------------------------------------
def test_static_part_without_check_pose_reports_no_collisions(server, write_script):
    build(server, write_script, "static")
    status, r = server.call("POST", "/api/check", {"m": "static", "values": {}})
    assert status == 200 and r == {"ok": True, "collisions": []}


def test_check_pose_of_the_models_script_is_used(server, write_script):
    build(server, write_script, "mech", "mech")
    r = server.call("POST", "/api/check", {"m": "mech", "values": {"j": 7}})[1]
    assert r == {"ok": True, "collisions": [["a", "b", 7]]}


def test_changed_script_is_reloaded(server, write_script):
    path = write_script("mech", "mech")
    server.call("POST", "/api/build", {"script": "mech"})
    server.call("POST", "/api/check", {"m": "mech", "values": {}})
    time.sleep(0.05)
    path.write_text(path.read_text().replace('int(values.get("j", 0))', "99"))
    assert server.call("POST", "/api/check", {"m": "mech", "values": {}})[1]["collisions"][0][2] == 99


def test_check_of_unknown_model_is_a_clean_error(server):
    status, r = server.call("POST", "/api/check", {"m": "ghost", "values": {}})
    assert status == 404 and r["ok"] is False


# ---- parameters ----------------------------------------------------------------------------------------------------
def test_params_are_saved_per_model_and_rebuild_that_model(server, write_script):
    build(server, write_script, "m1", "mech")
    build(server, write_script, "m2", "mech")
    status, r = server.call("POST", "/api/params", {"m": "m1", "values": {"w": 40}})
    assert status == 200 and r["ok"], r
    m1 = server.call("GET", "/api/model?m=m1")[1]
    m2 = server.call("GET", "/api/model?m=m2")[1]
    assert m1["params"][0]["value"] == 40 and m1["parts"][0]["bbox"][3] == 20
    assert m2["params"][0]["value"] == 10                       # other model untouched


def test_params_rebuild_failure_is_reported(server, write_script):
    path = write_script("bad", "mech")
    server.call("POST", "/api/build", {"script": "bad"})
    path.write_text("raise RuntimeError('boom')")
    r = server.call("POST", "/api/params", {"m": "bad", "values": {"w": 1}})[1]
    assert r["ok"] is False and "boom" in r["error"]


# ---- chat bridge ---------------------------------------------------------------------------------------------------
def test_messages_land_in_the_inbox_with_their_model(server):
    status, r = server.call("POST", "/api/message", {"m": "table", "text": "make it taller", "parts": ["leg_1"]})
    assert status == 200 and r["ok"]
    line = json.loads((server.root / ".cad" / "inbox.jsonl").read_text().splitlines()[-1])
    assert line["text"] == "make it taller" and line["model"] == "table" and line["parts"] == ["leg_1"]
    assert server.call("GET", "/api/chat")[1][-1]["text"] == "make it taller"
