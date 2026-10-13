"""Acceptance tests for the example mechanism: every preset must be collision-free and have the expected size."""
import runpy
from pathlib import Path

import pytest
from build123d import Compound

SCRIPT = Path(__file__).resolve().parents[2] / "parts" / "folding_table.py"


@pytest.fixture(scope="module")
def ns(tmp_path_factory):
    import os
    root = tmp_path_factory.mktemp("proj")
    os.environ["CADCHAT_ROOT"] = str(root)
    yield runpy.run_path(str(SCRIPT), run_name="test")
    os.environ.pop("CADCHAT_ROOT", None)


def size(ns, values):
    bb = Compound([s for _, s in ns["posed"](values)]).bounding_box()
    return round(bb.size.X), round(bb.size.Y), round(bb.size.Z)


def test_structure(ns):
    assert len(ns["parts"]) == 33 and len(ns["joints"]) == 8
    assert set(ns["presets"]) == {"open", "half", "closed"}
    assert all(p["role"] for p in ns["parts"]) and all(p["material"] for p in ns["parts"])


def test_open_size_is_centre_plus_four_flaps(ns):
    assert size(ns, ns["presets"]["open"]) == (2834, 900, 720)


def test_closed_is_a_slim_slab(ns):
    x, y, z = size(ns, ns["presets"]["closed"])
    assert x < 300 and y == 900 and z == 720


def test_half_is_the_centre_plus_inner_flaps(ns):
    assert size(ns, ns["presets"]["half"])[0] == 1583


@pytest.mark.parametrize("preset", ["open", "half", "closed"])
def test_every_preset_is_collision_free(ns, preset):
    assert ns["check_pose"](ns["presets"][preset]) == []


def test_a_wrong_pose_is_caught_and_names_the_clashing_parts(ns):
    closed_flaps_open_legs = dict(ns["presets"]["closed"], arm_front_R=0, arm_back_R=0, arm_front_L=0, arm_back_L=0)
    hits = ns["check_pose"](closed_flaps_open_legs)
    assert any({"flap_inner_R", "arm_rail_front_R"} == set(h[:2]) for h in hits)


def test_mirrored_sides_are_symmetric(ns):
    posed = dict(ns["posed"](ns["presets"]["closed"]))
    r, l = posed["flap_inner_R"].bounding_box(), posed["flap_inner_L"].bounding_box()
    assert round(r.min.X + l.max.X, 1) == 0 and round(r.max.X + l.min.X, 1) == 0
