"""The bundled static examples: shaft with a keyway and an L-bracket. Volumes were checked by hand."""
import json
import os
import subprocess
import sys

import pytest

from conftest import REPO


def build(project, name, params=None):
    d = project / ".cad" / "models" / name
    if params:
        d.mkdir(parents=True, exist_ok=True)
        (d / "params.json").write_text(json.dumps(params), encoding="utf-8")
    env = {**os.environ, "CADCHAT_ROOT": str(project)}
    r = subprocess.run([sys.executable, str(REPO / "library" / "parts" / f"{name}.py")], cwd=project, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads((d / "model.json").read_text(encoding="utf-8"))


def test_shaft_default_volume_and_size(project):
    m = build(project, "shaft")
    p = m["parts"][0]
    assert abs(p["volume"] - 30576.5) < 1          # 100 x d20 cylinder, chamfered, minus the keyway
    assert [round(v) for v in p["bbox"][3:]] == [10, 10, 100]
    assert p["material"]


def test_shaft_follows_its_parameters(project):
    m = build(project, "shaft", {"length": 120, "dia": 25})
    bb = m["parts"][0]["bbox"]
    assert round(bb[5] - bb[2]) == 120 and round(bb[3] - bb[0]) == 25
    assert {p["name"] for p in m["params"]} >= {"length", "dia", "key_w", "key_depth"}


def test_bracket_default_volume_and_size(project):
    p = build(project, "bracket")["parts"][0]
    assert abs(p["volume"] - 20526.8) < 1
    assert [round(b - a) for a, b in zip(p["bbox"][:3], p["bbox"][3:])] == [60, 40, 35]


def test_bracket_hole_count_matters(project):
    solid = build(project, "bracket", {"hole_d": 0.5})["parts"][0]["volume"]
    holed = build(project, "bracket", {"hole_d": 6})["parts"][0]["volume"]
    # six holes of 5 mm depth: 6 * pi * (3^2 - 0.25^2) * 5 = 843 mm3
    assert abs((solid - holed) - 843) < 15
