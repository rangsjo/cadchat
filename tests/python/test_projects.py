"""Projects (a folder with cadproject.json, its own parts/, exports/, .cad/ and chat history), the registry of known projects and
the library of reusable models that `add` copies into a project."""
import json

import pytest

import projects


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "cfg"
    monkeypatch.setenv("CADCHAT_HOME", str(h))
    return h


def test_init_creates_the_project_skeleton(tmp_path, home):
    p = projects.init_project(tmp_path / "chairs", name="Dining chairs")
    assert projects.is_project(p)
    meta = json.loads((p / "cadproject.json").read_text(encoding="utf-8"))
    assert meta["name"] == "Dining chairs" and meta["created"]
    for d in ("parts", "exports", ".cad"):
        assert (p / d).is_dir()
    assert ".cad/" in (p / ".gitignore").read_text(encoding="utf-8")


def test_init_defaults_the_name_to_the_folder_and_refuses_an_existing_project(tmp_path, home):
    p = projects.init_project(tmp_path / "shelf")
    assert projects.project_name(p) == "shelf"
    with pytest.raises(FileExistsError):
        projects.init_project(p)


def test_init_registers_the_project_and_known_projects_lists_most_recent_first(tmp_path, home):
    a = projects.init_project(tmp_path / "a")
    b = projects.init_project(tmp_path / "b")
    assert [x["path"] for x in projects.known_projects()] == [str(b), str(a)]
    projects.touch(a)
    assert [x["path"] for x in projects.known_projects()] == [str(a), str(b)]


def test_known_projects_forgets_folders_that_no_longer_exist(tmp_path, home):
    a = projects.init_project(tmp_path / "a")
    import shutil
    shutil.rmtree(a)
    assert projects.known_projects() == []


def test_resolution_order_option_then_env_then_cwd_then_last_used_then_examples(tmp_path, home, monkeypatch):
    a, b, c = (projects.init_project(tmp_path / n) for n in "abc")
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.delenv("CADCHAT_ROOT", raising=False)
    assert projects.resolve_project(str(a), env={"CADCHAT_ROOT": str(b)}, cwd=c) == a              # --project wins
    assert projects.resolve_project(None, env={"CADCHAT_ROOT": str(b)}, cwd=c) == b                # then the environment
    assert projects.resolve_project(None, env={}, cwd=c / "parts") == c                            # then the project around the cwd
    projects.touch(a)
    assert projects.resolve_project(None, env={}, cwd=nowhere) == a                                # then the last used one
    (home / "projects.json").unlink()
    assert projects.resolve_project(None, env={}, cwd=nowhere) == projects.EXAMPLES                # finally the bundled examples


def test_resolving_a_folder_that_is_not_a_project_is_an_error(tmp_path, home):
    with pytest.raises(ValueError):
        projects.resolve_project(str(tmp_path), env={}, cwd=tmp_path)


def test_library_lists_reusable_models(home):
    names = projects.library_list()
    assert {"shaft", "bracket"} <= set(names)


def test_add_copies_a_library_model_into_the_project_and_makes_it_runnable_from_there(tmp_path, home):
    p = projects.init_project(tmp_path / "proj")
    f = projects.add_from_library("shaft", p)
    assert f == p / "parts" / "shaft.py"
    text = f.read_text(encoding="utf-8")
    assert str(projects.TOOLS) in text and "parents[2]" not in text         # finds the app's tools from anywhere
    g = projects.add_from_library("shaft", p, as_name="long_shaft")
    assert "parts/long_shaft.py" in g.read_text(encoding="utf-8") and "exports/long_shaft" in g.read_text(encoding="utf-8")


def test_add_refuses_unknown_models_bad_names_and_overwrites(tmp_path, home):
    p = projects.init_project(tmp_path / "proj")
    with pytest.raises(ValueError):
        projects.add_from_library("nope", p)
    with pytest.raises(ValueError):
        projects.add_from_library("shaft", p, as_name="../x")
    projects.add_from_library("shaft", p)
    with pytest.raises(FileExistsError):
        projects.add_from_library("shaft", p)


def test_pick_port_skips_ports_in_use():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    busy = s.getsockname()[1]
    try:
        assert projects.pick_port(busy) != busy
    finally:
        s.close()
