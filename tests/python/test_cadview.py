import json
import subprocess
import sys

import cadview


def run(script):
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)


def test_publish_goes_to_a_directory_named_after_the_script(project, write_script):
    run(write_script("bracket"))
    m = json.loads((project / ".cad" / "models" / "bracket" / "model.json").read_text())
    assert m["name"] == "bracket"
    assert [p["name"] for p in m["parts"]] == ["block"]
    assert (project / ".cad" / "models" / "bracket" / "script").read_text() == "parts/bracket.py"


def test_two_scripts_publish_side_by_side(project, write_script):
    run(write_script("a"))
    run(write_script("b"))
    assert sorted(p.name for p in (project / ".cad" / "models").iterdir()) == ["a", "b"]


def test_published_part_bbox_and_volume(project, write_script):
    run(write_script("blk"))
    p = json.loads((project / ".cad" / "models" / "blk" / "model.json").read_text())["parts"][0]
    assert p["bbox"] == [-5, -10, -15, 5, 10, 15]
    assert abs(p["volume"] - 6000) < 1


def test_params_override_comes_from_the_models_own_file(project, write_script):
    script = write_script("m", "mech")
    d = project / ".cad" / "models" / "m"
    d.mkdir(parents=True)
    (d / "params.json").write_text(json.dumps({"w": 50}))
    run(script)
    m = json.loads((d / "model.json").read_text())
    assert m["params"][0]["value"] == 50 and m["params"][0]["default"] == 10
    assert m["parts"][0]["bbox"][3] == 25


def test_load_params_ignores_other_models(project):
    other = project / ".cad" / "models" / "other"
    other.mkdir(parents=True)
    (other / "params.json").write_text(json.dumps({"w": 99}))
    assert cadview.load_params(project / "parts" / "mine.py", {"w": (10, "mm", "g", "d")}) == {"w": 10.0}


def test_role_and_material_are_published(project):
    from build123d import Box
    cadview.publish_kinematic([dict(name="leg_1", shape=Box(1, 1, 1), joint=None, role="leg", material="oak")],
                              [], {"default": {}}, "parts/x.py")
    p = json.loads((project / ".cad" / "models" / "x" / "model.json").read_text())["parts"][0]
    assert (p["role"], p["material"]) == ("leg", "oak")
