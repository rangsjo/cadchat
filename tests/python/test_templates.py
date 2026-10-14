"""The templates are what new models start from: they must run unchanged in an empty project."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO


def instantiate(project, template, name):
    text = (REPO / "templates" / template).read_text(encoding="utf-8").replace("NAME", name)
    f = project / "parts" / f"{name}.py"
    f.write_text(text.replace('Path(__file__).resolve().parent.parent / "tools"', f'Path(r"{REPO / "tools"}")'), encoding="utf-8")
    return f


def run(project, f):
    r = subprocess.run([sys.executable, str(f)], cwd=project, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads((project / ".cad" / "models" / f.stem / "model.json").read_text(encoding="utf-8"))


def test_part_template_runs_and_publishes(project):
    m = run(project, instantiate(project, "part.py", "plate"))
    assert [p["name"] for p in m["parts"]] == ["plate"] and m["joints"] == []
    assert (project / "exports" / "plate.step").exists() and (project / "exports" / "plate.stl").exists()
    assert "plate" in (project / "exports" / "plate.step").read_text(encoding="utf-8", errors="ignore")      # named product, not anonymous geometry


def test_mechanism_template_runs_and_publishes_a_working_hinge(project):
    m = run(project, instantiate(project, "mechanism.py", "box"))
    assert {p["name"] for p in m["parts"]} == {"body", "lid"}
    assert [j["name"] for j in m["joints"]] == ["lid_hinge"] and set(m["presets"]) == {"closed", "open"}
    assert [p["name"] for p in m["params"]] == ["w", "d", "h", "wall"]
    step = (project / "exports" / "box_open.step").read_text(encoding="utf-8", errors="ignore")
    assert step.count("PRODUCT(") == 3 and "body" in step and "lid" in step              # an assembly tree for other CAD systems


def test_mechanism_template_exposes_check_pose(project):
    import runpy, os
    f = instantiate(project, "mechanism.py", "box2")
    ns = runpy.run_path(str(f), run_name="x")
    assert ns["check_pose"]({"lid_hinge": 0}) == []
    assert ns["check_pose"]({"lid_hinge": -90})              # lid swung into the box
