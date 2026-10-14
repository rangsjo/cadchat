import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import pytest


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An empty cadchat project in a temp dir; cadview/cadserver use it through CADCHAT_ROOT."""
    (tmp_path / "parts").mkdir()
    monkeypatch.setenv("CADCHAT_ROOT", str(tmp_path))
    return tmp_path


STATIC_SCRIPT = '''
import sys
sys.path.insert(0, r"{tools}")
from build123d import Box
from cadview import publish_kinematic
if __name__ == "__main__":
    publish_kinematic([dict(name="block", shape=Box(10, 20, 30), joint=None)], [], {{"default": {{}}}}, "parts/{name}.py")
'''

MECH_SCRIPT = '''
import sys
sys.path.insert(0, r"{tools}")
from build123d import Box
from cadview import publish_kinematic, load_params, params_out
PARAMS = {{"w": (10, "mm", "g", "width")}}
V = load_params(__file__, PARAMS)
def check_pose(values):
    return [["a", "b", int(values.get("j", 0))]]
if __name__ == "__main__":
    publish_kinematic([dict(name="block", shape=Box(V["w"], 20, 30), joint=None)], [], {{"default": {{}}}},
                      "parts/{name}.py", params_out(PARAMS, V))
'''


@pytest.fixture
def write_script(project):
    def _w(name, kind="static"):
        text = (STATIC_SCRIPT if kind == "static" else MECH_SCRIPT).format(tools=str(REPO / "tools"), name=name)
        (project / "parts" / f"{name}.py").write_text(text, encoding="utf-8")
        return project / "parts" / f"{name}.py"
    return _w
