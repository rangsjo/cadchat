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
    s.port, s.token, s.root, s.httpd = port, token, project, httpd

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
    (server.root / "parts" / "_private.py").write_text("x = 1", encoding="utf-8")
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
    path.write_text(path.read_text(encoding="utf-8").replace('int(values.get("j", 0))', "99"))
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
    path.write_text("raise RuntimeError('boom')", encoding="utf-8")
    r = server.call("POST", "/api/params", {"m": "bad", "values": {"w": 1}})[1]
    assert r["ok"] is False and "boom" in r["error"]


# ---- chat bridge ---------------------------------------------------------------------------------------------------
def test_messages_land_in_the_inbox_with_their_model(server):
    status, r = server.call("POST", "/api/message", {"m": "table", "text": "make it taller", "parts": ["leg_1"]})
    assert status == 200 and r["ok"]
    line = json.loads((server.root / ".cad" / "inbox.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert line["text"] == "make it taller" and line["model"] == "table" and line["parts"] == ["leg_1"]
    assert server.call("GET", "/api/chat")[1][-1]["text"] == "make it taller"


# ---- speed: polling must stay cheap, rebuilds must reuse a warm interpreter --------------------------------------------
def test_version_only_stats_files_it_never_parses_them(server, write_script):
    build(server, write_script, "a")
    (server.root / ".cad" / "models" / "a" / "model.json").write_text("this is not json", encoding="utf-8")
    status, r = server.call("GET", "/api/version")
    assert status == 200 and "a" in r["models"]


def test_model_listing_is_cached_until_the_file_changes(server, write_script, monkeypatch):
    build(server, write_script, "a")
    real, calls = json.loads, []
    monkeypatch.setattr(cadserver.json, "loads", lambda s, *a, **k: (calls.append(1) if '"constraints"' in str(s) else None, real(s, *a, **k))[1])      # count model.json parses only
    server.call("GET", "/api/models")
    server.call("GET", "/api/models")
    assert len(calls) == 1
    time.sleep(0.05)
    server.call("POST", "/api/build", {"script": "a"})
    server.call("GET", "/api/models")
    assert len(calls) == 2


def test_rebuilds_are_served_by_one_warm_worker(server, write_script):
    build(server, write_script, "a")
    pid1 = server.httpd.app.worker.pid
    server.call("POST", "/api/build", {"script": "a"})
    assert pid1 and server.httpd.app.worker.pid == pid1


def test_worker_survives_a_failing_script(server, write_script):
    path = write_script("bad", "mech")
    build(server, write_script, "good")
    pid = server.httpd.app.worker.pid
    path.write_text("raise RuntimeError('boom')", encoding="utf-8")
    assert server.call("POST", "/api/build", {"script": "bad"})[1]["ok"] is False
    assert server.call("POST", "/api/build", {"script": "good"})[1]["ok"] is True
    assert server.httpd.app.worker.pid == pid


# ---- import through the API ------------------------------------------------------------------------------------------
def test_uploaded_step_file_becomes_a_model(server, tmp_path):
    from build123d import Box
    import exchange
    f = tmp_path / "u.step"
    exchange.export_step_assembly([("slab", Box(10, 20, 5))], f, name="u")
    data = f.read_bytes()
    c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=120)
    c.request("POST", "/api/import?name=slab&ext=step", data, {"Host": f"127.0.0.1:{server.port}", "X-CAD-Token": server.token})
    r = c.getresponse()
    body = json.loads(r.read())
    assert r.status == 200 and body["ok"], body
    m = server.call("GET", "/api/model?m=slab")[1]
    assert [p["name"] for p in m["parts"]] == ["slab"]
    assert server.call("POST", "/api/check", {"m": "slab", "values": {}})[1] == {"ok": True, "collisions": []}     # imported: no script


def test_upload_rejects_bad_names_types_and_missing_token(server):
    ok_host = {"Host": f"127.0.0.1:{server.port}"}
    for query, hdr, code in [("name=../x&ext=step", {"X-CAD-Token": server.token}, 400),
                             ("name=a&ext=exe", {"X-CAD-Token": server.token}, 400),
                             ("name=a&ext=step", {}, 403)]:
        c = http.client.HTTPConnection("127.0.0.1", server.port, timeout=30)
        c.request("POST", f"/api/import?{query}", b"x", {**ok_host, **hdr})
        assert c.getresponse().status == code, query


# ---- restarts must not break open pages -------------------------------------------------------------------------------
def test_token_survives_a_server_restart(project):
    _, t1 = cadserver.make_server(project, port=0)
    _, t2 = cadserver.make_server(project, port=0)
    assert t1 == t2 and len(t1) >= 16
    assert (project / ".cad" / "token").read_text(encoding="utf-8").strip() == t1


def test_a_damaged_token_file_is_replaced(project):
    (project / ".cad").mkdir()
    (project / ".cad" / "token").write_text("x", encoding="utf-8")
    _, t = cadserver.make_server(project, port=0)
    assert len(t) >= 16 and (project / ".cad" / "token").read_text(encoding="utf-8").strip() == t


# ---- is the assistant listening? ------------------------------------------------------------------------------------------------
def write_cad(root, name, *objs):
    (root / ".cad").mkdir(exist_ok=True)
    with open(root / ".cad" / name, "a", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o) + "\n")


def test_assistant_unknown_until_a_watcher_has_run(server):
    r = server.call("GET", "/api/assistant")[1]
    assert r["listening"] is False and r["last_seen"] is None and r["pending"] == 0


def test_assistant_listening_follows_the_heartbeat(server):
    (server.root / ".cad").mkdir(exist_ok=True)
    hb = {"beat": time.time(), "since": time.time() - 60, "pid": 1, "listening": True}
    (server.root / ".cad" / "assistant.json").write_text(json.dumps(hb), encoding="utf-8")
    r = server.call("GET", "/api/assistant")[1]
    assert r["listening"] is True and r["since"] == pytest.approx(hb["since"])
    hb["beat"] = time.time() - 30
    (server.root / ".cad" / "assistant.json").write_text(json.dumps(hb), encoding="utf-8")
    r = server.call("GET", "/api/assistant")[1]
    assert r["listening"] is False and r["last_seen"] == pytest.approx(hb["beat"])


def test_a_stopped_watcher_is_not_listening_even_with_a_fresh_beat(server):
    (server.root / ".cad").mkdir(exist_ok=True)
    (server.root / ".cad" / "assistant.json").write_text(json.dumps({"beat": time.time(), "since": 1, "listening": False}), encoding="utf-8")
    assert server.call("GET", "/api/assistant")[1]["listening"] is False


def test_pending_counts_messages_nobody_answered(server):
    write_cad(server.root, "chat.jsonl", {"id": "a", "role": "user", "text": "1"}, {"id": "r", "role": "assistant", "text": "ok"},
              {"id": "b", "role": "user", "text": "2"}, {"id": "c", "role": "user", "text": "3"})
    assert server.call("GET", "/api/assistant")[1]["pending"] == 2


def test_chat_messages_carry_a_delivery_state(server):
    write_cad(server.root, "chat.jsonl", {"id": "a", "role": "user", "text": "1"}, {"id": "b", "role": "user", "text": "2"},
              {"id": "c", "role": "user", "text": "3"}, {"id": "s", "role": "status", "text": "working"}, {"id": "d", "role": "user", "text": "4"},
              {"id": "r", "role": "assistant", "text": "done"}, {"id": "e", "role": "user", "text": "5"})
    write_cad(server.root, "seen.jsonl", {"id": "b", "t": 1}, {"id": "c", "t": 1}, {"id": "d", "t": 1})
    states = {m["id"]: m.get("state") for m in server.call("GET", "/api/chat")[1] if m["role"] == "user"}
    # a: queued then answered by r; b,c: seen then a status line; d: seen then answered; e: queued
    assert states == {"a": "answered", "b": "answered", "c": "answered", "d": "answered", "e": "queued"}


def test_chat_states_queued_seen_working(server):
    write_cad(server.root, "chat.jsonl", {"id": "a", "role": "user", "text": "1"}, {"id": "b", "role": "user", "text": "2"},
              {"id": "s", "role": "status", "text": "working"}, {"id": "c", "role": "user", "text": "3"})
    write_cad(server.root, "seen.jsonl", {"id": "b", "t": 1}, {"id": "c", "t": 1})
    states = {m["id"]: m.get("state") for m in server.call("GET", "/api/chat")[1] if m["role"] == "user"}
    assert states == {"a": "queued", "b": "working", "c": "seen"}


# ---- projects, per-model chat, history --------------------------------------------------------------------------
def test_version_names_the_project(server):
    (server.root / "cadproject.json").write_text('{"name": "Chairs"}', encoding="utf-8")
    s, v = server.call("GET", "/api/version")
    assert v["project"] == str(server.root.resolve()) and v["name"] in ("Chairs", server.root.name)


def post_msg(server, text, model):
    assert server.call("POST", "/api/message", {"text": text, "m": model})[1]["ok"]


def test_chat_can_be_limited_to_one_model(server):
    post_msg(server, "about a", "a")
    post_msg(server, "about b", "b")
    texts = lambda path: [m["text"] for m in server.call("GET", path)[1]]
    assert texts("/api/chat") == ["about a", "about b"]
    assert texts("/api/chat?m=a") == ["about a"] and texts("/api/chat?m=b") == ["about b"]


def test_history_lists_snapshots_and_restore_rebuilds_the_old_state(server, write_script):
    write_script("m", "mech")
    s, r = server.call("POST", "/api/build", {"script": "m"})
    assert r["ok"]
    first = server.call("GET", "/api/history?m=m")[1]
    assert len(first) == 1
    server.call("POST", "/api/params", {"m": "m", "values": {"w": 33}})
    hist = server.call("GET", "/api/history?m=m")[1]
    assert len(hist) == 2
    s, r = server.call("POST", "/api/restore", {"m": "m", "id": hist[-1]["id"]})
    assert r["ok"]
    model = server.call("GET", "/api/model?m=m")[1]
    assert model["params"][0]["value"] == 10                                  # the first snapshot had the default width
    assert server.call("POST", "/api/restore", {"m": "m", "id": "nope"})[0] in (200, 404)


def test_assistant_can_be_started_from_the_viewer(server, tmp_path, monkeypatch):
    import launcher
    seen = []
    monkeypatch.setattr(launcher, "start_assistant", lambda root, **k: seen.append(str(root)) or "started")
    s, r = server.call("POST", "/api/assistant/start", {})
    assert s == 200 and r == {"ok": True, "state": "started"} and seen == [str(server.root.resolve())]
    assert server.call("POST", "/api/assistant/start", {}, token=None)[0] == 403


# ---- menu backend: settings, projects, new model, saved versions, exports, joints --------------------------------------
@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("CADCHAT_HOME", str(tmp_path / "cfg"))
    for v in ("CADCHAT_ASSISTANT_CMD", "CADCHAT_TERMINAL"):
        monkeypatch.delenv(v, raising=False)
    return tmp_path


def test_settings_can_be_read_and_changed(server, cfg):
    s, r = server.call("GET", "/api/settings")
    assert r["assistant_cmd"] == "claude"
    s, r = server.call("POST", "/api/settings", {"assistant_cmd": "myagent"})
    assert r["ok"] and server.call("GET", "/api/settings")[1]["assistant_cmd"] == "myagent"
    s, r = server.call("POST", "/api/settings", {"clearance": -5})
    assert not r["ok"] and "clearance" in r["error"]
    assert server.call("POST", "/api/settings", {"assistant_cmd": "x"}, token=None)[0] == 403


def test_projects_listing_marks_the_current_one(server, cfg):
    import projects
    (server.root / "cadproject.json").write_text('{"name": "Here"}', encoding="utf-8")
    projects.touch(server.root)
    other = projects.init_project(cfg / "other")
    s, r = server.call("GET", "/api/projects")
    cur = [p for p in r["projects"] if p["current"]]
    assert [p["path"] for p in cur] == [str(server.root.resolve())] and any(p["path"] == str(other) for p in r["projects"])


def test_a_new_project_is_created_in_the_projects_folder_and_served(server, cfg, monkeypatch):
    import cadchat, projects, settings
    settings.save({"projects_dir": str(cfg / "work")})
    monkeypatch.setattr(cadchat, "start_server", lambda root, *a, **k: {"url": "http://127.0.0.1:9999/", "port": 9999, "started": True, "pid": 1})
    s, r = server.call("POST", "/api/project/new", {"name": "Dining chairs"})
    assert r["ok"] and r["url"] == "http://127.0.0.1:9999/"
    assert projects.is_project(cfg / "work" / "Dining-chairs") and projects.project_name(cfg / "work" / "Dining-chairs") == "Dining chairs"
    assert not server.call("POST", "/api/project/new", {"name": "../evil"})[1]["ok"]


def test_opening_a_project_only_works_for_projects(server, cfg, monkeypatch):
    import cadchat, projects
    monkeypatch.setattr(cadchat, "start_server", lambda root, *a, **k: {"url": f"http://127.0.0.1:9998/", "port": 9998, "started": True, "pid": 1})
    p = projects.init_project(cfg / "other")
    assert server.call("POST", "/api/project/open", {"path": str(p)})[1]["url"].startswith("http://127.0.0.1:")
    assert not server.call("POST", "/api/project/open", {"path": str(cfg)})[1]["ok"]


def test_new_model_from_a_template_or_the_library_is_built(server, cfg):
    s, r = server.call("POST", "/api/model/new", {"kind": "part", "name": "plate"})
    assert r["ok"] and server.call("GET", "/api/model?m=plate")[0] == 200
    s, r = server.call("POST", "/api/model/new", {"library": "shaft", "name": "rod"})
    assert r["ok"] and server.call("GET", "/api/model?m=rod")[0] == 200
    assert not server.call("POST", "/api/model/new", {"kind": "part", "name": "plate"})[1]["ok"]            # exists
    assert not server.call("POST", "/api/model/new", {"library": "nope", "name": "x"})[1]["ok"]


def test_save_version_keeps_a_named_snapshot(server, write_script):
    write_script("m", "mech")
    server.call("POST", "/api/build", {"script": "m"})
    s, r = server.call("POST", "/api/version/save", {"m": "m", "note": "good state"})
    assert r["ok"]
    hist = server.call("GET", "/api/history?m=m")[1]
    assert hist[0]["note"] == "good state" and len(hist) == 2


def test_exports_are_listed_and_downloadable_from_the_exports_folder_only(server, write_script):
    (server.root / "exports").mkdir()
    (server.root / "exports" / "m_open.step").write_text("STEP", encoding="utf-8")
    (server.root / "exports" / "other.stl").write_text("STL", encoding="utf-8")
    s, r = server.call("GET", "/api/exports?m=m")
    assert [f["name"] for f in r] == ["m_open.step"]
    s, body = server.call("GET", "/api/export/file?name=m_open.step")
    assert s == 200 and body == "STEP"
    assert server.call("GET", "/api/export/file?name=../.cad/token")[0] in (400, 404)


def test_joint_library_lists_kinds_with_proportions_for_a_thickness(server):
    s, r = server.call("GET", "/api/joints?t=18")
    kinds = {j["kind"]: j for j in r}
    assert {"dowel_butt", "dado", "rabbet", "half_lap", "mortise_tenon"} <= set(kinds)
    assert kinds["mortise_tenon"]["defaults"]["tenon_t"] == 6 and kinds["dado"]["description"]


def test_library_listing(server):
    s, r = server.call("GET", "/api/library")
    assert "shaft" in r and "joinery_demo" in r


def test_the_workshop_site_can_be_built_from_the_viewer(server, write_script):
    write_script("m", "mech")
    server.call("POST", "/api/build", {"script": "m"})
    s, r = server.call("POST", "/api/share/build", {"m": "m"})
    assert r["ok"] and "m.html" in r["files"] and (server.root / "share" / "m.html").exists() and r["path"].endswith("share")
    assert server.call("POST", "/api/share/build", {}, token=None)[0] == 403


def test_usage_endpoint_reads_the_configured_transcripts(server, tmp_path):
    import json as _j, settings, time as _t
    d = tmp_path / "tr"
    d.mkdir()
    (d / "s.jsonl").write_text(_j.dumps({"cwd": str(server.root.resolve())}) + "\n" + _j.dumps({"type": "assistant", "timestamp": _t.strftime("%Y-%m-%dT00:00:00Z", _t.gmtime()),
        "message": {"id": "a", "model": "m", "usage": {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4}}}) + "\n", encoding="utf-8")
    settings.save({"usage_dirs": str(d)})
    s, r = server.call("GET", "/api/usage")
    assert r["total"]["output"] == 2 and r["today"]["cache_read"] == 3 and r["sources"] == 1


def test_clearing_the_chat_archives_it_and_starts_empty(server):
    import json as _j
    post_msg(server, "first question", "a")
    post_msg(server, "second question", "b")
    s, r = server.call("POST", "/api/chat/clear", {})
    assert r["ok"] and r["archived"] == 2
    assert server.call("GET", "/api/chat")[1] == []
    files = list((server.root / ".cad" / "chat-archive").glob("*.jsonl"))
    assert len(files) == 1 and "first question" in files[0].read_text(encoding="utf-8") and r["file"].endswith(files[0].name)
    last = _j.loads((server.root / ".cad" / "inbox.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert last["role"] == "system" and "cleared" in last["text"]                          # a running assistant is told
    assert server.call("POST", "/api/chat/clear", {})[1]["archived"] == 0                  # nothing to archive: no empty file
    assert len(list((server.root / ".cad" / "chat-archive").glob("*.jsonl"))) == 1
    assert server.call("POST", "/api/chat/clear", {}, token=None)[0] == 403


def test_messages_after_a_clear_are_new_and_old_ones_are_not_replayed(server):
    import io
    from cadwatch import Watcher
    post_msg(server, "old", "a")
    server.call("POST", "/api/chat/clear", {})
    post_msg(server, "new", "a")
    out = []
    w = Watcher(server.root, out=out.append)
    w.start()
    assert [__import__("json").loads(x)["text"] for x in out] == ["new"]                   # only the message sent after the clear
    assert server.call("GET", "/api/chat")[1][0]["text"] == "new"


def test_clearing_the_chat_also_resets_the_assistant_session(server, monkeypatch):
    import launcher
    calls = []
    monkeypatch.setattr(launcher, "restart_assistant", lambda root: calls.append(str(root)) or "restarted")
    post_msg(server, "a screenshot of an old error", "a")
    s, r = server.call("POST", "/api/chat/clear", {})
    assert r["ok"] and r["assistant"] == "restarted" and calls == [str(server.root.resolve())]


def test_providers_endpoint_lists_the_agents_and_the_current_choice(server):
    s, r = server.call("GET", "/api/providers")
    assert [p["id"] for p in r["providers"]][:4] == ["claude", "copilot", "codex", "gemini"]
    assert r["current"] == {"provider": "claude", "assistant_mode": "session", "setup_done": False}
    assert r["providers"][0]["login"] and r["providers"][1]["install"]


def test_a_provider_can_be_tested_and_the_choice_saved(server, monkeypatch):
    import providers
    def fake_detect(pid, timeout=8.0):
        providers.get(pid)                                              # unknown ids raise KeyError like the real one
        return {"installed": pid == "claude", "path": "/x/" + pid, "version": "1.0"}
    monkeypatch.setattr(providers, "detect", fake_detect)
    s, r = server.call("POST", "/api/providers/test", {"id": "claude"})
    assert r["ok"] and r["installed"] is True and r["version"] == "1.0"
    assert server.call("POST", "/api/providers/test", {"id": "copilot"})[1]["installed"] is False
    assert not server.call("POST", "/api/providers/test", {"id": "nope"})[1]["ok"]
    assert server.call("POST", "/api/providers/test", {"id": "claude"}, token=None)[0] == 403
    s, r = server.call("POST", "/api/settings", {"provider": "copilot", "assistant_mode": "message", "setup_done": True})
    assert r["ok"] and server.call("GET", "/api/providers")[1]["current"] == {"provider": "copilot", "assistant_mode": "message", "setup_done": True}


# ---- Creo link: state and commands go through files shared with tools/creolink.py -------------------------------------------
def write_creo_state(root, **kw):
    d = root / ".cad" / "creo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({"connected": True, "model": "bracket.prt", "updated": time.time(), **kw}), encoding="utf-8")


def test_creo_status_defaults_to_not_running(server):
    assert server.call("GET", "/api/creo")[1] == {"connected": False, "running": False}


def test_creo_status_passes_the_link_state_through(server):
    write_creo_state(server.root, params=[{"name": "d1", "value": 1.0}])
    r = server.call("GET", "/api/creo")[1]
    assert r["running"] is True and r["connected"] is True and r["model"] == "bracket.prt" and r["params"][0]["name"] == "d1"


def test_creo_status_goes_stale_when_the_link_stops_updating(server):
    write_creo_state(server.root, updated=time.time() - 60)
    r = server.call("GET", "/api/creo")[1]
    assert r["running"] is False and r["connected"] is False


def test_creo_commands_are_queued_for_the_link(server):
    r = server.call("POST", "/api/creo/command", {"cmd": "set", "name": "LENGTH", "value": 75.5})[1]
    assert r["ok"] and r["id"]
    server.call("POST", "/api/creo/command", {"cmd": "sync"})
    lines = [json.loads(l) for l in (server.root / ".cad" / "creo" / "commands.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(l["cmd"], l.get("name"), l.get("value")) for l in lines] == [("set", "LENGTH", 75.5), ("sync", None, None)]


@pytest.mark.parametrize("body", [
    {"cmd": "format_disk"}, {"cmd": "set"}, {"cmd": "set", "name": "x" * 200, "value": 1},
    {"cmd": "set", "name": "A", "value": [1]}, {"cmd": "set", "name": "A\nB", "value": 1}, {"cmd": "auto_sync"}])
def test_creo_commands_are_validated(server, body):
    assert server.call("POST", "/api/creo/command", body)[0] == 400


def test_creo_commands_need_the_token(server):
    assert server.call("POST", "/api/creo/command", {"cmd": "sync"}, token=None)[0] == 403


def test_features_lists_what_the_viewer_should_show(server):
    import settings
    s, r = server.call("GET", "/api/features")
    assert r["plugins"] == [] and [p["id"] for p in r["available"]] == ["creo"]
    settings.save({"plugins": "creo"})
    assert server.call("GET", "/api/features")[1]["plugins"] == ["creo"]
