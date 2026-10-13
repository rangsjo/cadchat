import pytest

import cadchat


def test_new_part_copies_the_template_with_the_name_filled_in(project):
    f = cadchat.create("part", "my_plate", project)
    assert f == project / "parts" / "my_plate.py"
    text = f.read_text()
    assert "NAME" not in text and 'parts/my_plate.py' in text and "exports/my_plate.step" in text


def test_new_mechanism_uses_the_mechanism_template(project):
    text = cadchat.create("mechanism", "lidbox", project).read_text()
    assert "Mechanism(" in text and "NAME" not in text


def test_new_refuses_to_overwrite_an_existing_script(project):
    cadchat.create("part", "a", project)
    with pytest.raises(FileExistsError):
        cadchat.create("part", "a", project)


@pytest.mark.parametrize("bad", ["", "../evil", "has space", "x/y", "a" * 80, "_private"])
def test_new_rejects_unsafe_names(project, bad):
    with pytest.raises(ValueError):
        cadchat.create("part", bad, project)


def test_new_rejects_unknown_kinds(project):
    with pytest.raises(ValueError):
        cadchat.create("spaceship", "x", project)


def test_list_shows_scripts_and_whether_they_are_built(project):
    cadchat.create("part", "built_one", project)
    cadchat.create("part", "unbuilt", project)
    (project / ".cad" / "models" / "built_one").mkdir(parents=True)
    (project / ".cad" / "models" / "built_one" / "model.json").write_text("{}")
    (project / "parts" / "_hidden.py").write_text("")
    assert cadchat.list_scripts(project) == [("built_one", True), ("unbuilt", False)]


def test_main_new_and_list_roundtrip(project, capsys):
    assert cadchat.main(["new", "part", "widget"], project) == 0
    assert cadchat.main(["list"], project) == 0
    assert "widget" in capsys.readouterr().out
    assert cadchat.main(["new", "part", "widget"], project) == 1      # already exists -> error exit code
