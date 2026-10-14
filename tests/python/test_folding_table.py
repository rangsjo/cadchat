"""Acceptance tests for the example mechanism: a folding drop-leaf table rebuilt from photos and the dealer's sizes.

Reference sizes (dealer listing): folded 23 cm wide, one leaf up 151 cm, fully open 280 cm, 90 cm deep, 73.5 cm high.
Structure seen in the photos: two thick vertical pillars side by side under two narrow centre strips (the caps); on each side a leaf of
two panels that hang under the caps when folded; ladder-shaped leg gates that swing out from the pillars on vertical hinges and fold
flat between pillar and hanging panels. The inner panel hangs from a hinge on the top side, the outer one folds under the inner one
(opposite sense).
"""
import runpy
from pathlib import Path

import pytest
from build123d import Compound

SCRIPT = Path(__file__).resolve().parents[2] / "parts" / "folding_table.py"
SIDES, GATES = "RL", ("front", "back")


@pytest.fixture(scope="module")
def ns(tmp_path_factory):
    import os
    root = tmp_path_factory.mktemp("proj")
    os.environ["CADCHAT_ROOT"] = str(root)
    yield runpy.run_path(str(SCRIPT), run_name="test")
    os.environ.pop("CADCHAT_ROOT", None)


def posed(ns, values):
    return dict(ns["posed"](values))


def bb(ns, values, name):
    return posed(ns, values)[name].bounding_box()


def size(ns, values):
    b = Compound(list(posed(ns, values).values())).bounding_box()
    return round(b.size.X), round(b.size.Y), round(b.size.Z)


# ---- structure ------------------------------------------------------------------------------------------------------------------
def test_structure(ns):
    assert len(ns["joints"]) == 8 and len(ns["parts"]) == 28
    assert set(ns["presets"]) == {"open", "one_leaf", "closed"}
    assert all(p["role"] for p in ns["parts"]) and all(p["material"] for p in ns["parts"])
    names = {p["name"] for p in ns["parts"]}
    assert {"pillar_R", "pillar_L", "cap_R", "cap_L"} <= names


def test_dealer_sizes(ns):
    p = ns["presets"]
    assert 2780 <= size(ns, p["open"])[0] <= 2820                  # 280 cm fully extended
    assert 1490 <= size(ns, p["one_leaf"])[0] <= 1530              # 151 cm with one leaf up
    assert 225 <= size(ns, p["closed"])[0] <= 235                  # 23 cm folded
    for k in ("open", "one_leaf", "closed"):
        x, y, z = size(ns, p[k])
        assert y == 900 and z == 735                               # 90 cm deep, 73.5 cm high


def test_closed_everything_is_inside_the_footprint_of_the_caps(ns):
    pose = ns["presets"]["closed"]
    for name, shape in posed(ns, pose).items():
        b = shape.bounding_box()
        assert -ns["half_c"] - 0.5 <= b.min.X and b.max.X <= ns["half_c"] + 0.5, name


# ---- hinges ---------------------------------------------------------------------------------------------------------------------
def test_inner_leaf_hangs_from_the_top_side_outer_leaf_folds_under_the_inner_one(ns):
    j = {x["name"]: x for x in ns["joints"]}
    assert j["flap_inner_R"]["origin"][2] > ns["uz"]                # hinge pin in the top skin of the cap
    assert j["flap_outer_R"]["origin"][2] == ns["uz"]               # hinge on the underside: the other way round
    assert j["flap_outer_R"]["parent"] == "flap_inner_R"


def test_gates_turn_about_vertical_axes_in_opposite_senses(ns):
    j = {x["name"]: x for x in ns["joints"]}
    f, b = j["gate_front_R"], j["gate_back_R"]
    assert f["axis"][:2] == [0, 0] and b["axis"][:2] == [0, 0] and f["axis"][2] == -b["axis"][2] != 0
    assert f["origin"][1] > 0 > b["origin"][1]


def test_open_gates_carry_the_inner_leaf_and_swing_flat_when_closed(ns):
    pose = ns["presets"]["open"]
    leaf = bb(ns, pose, "flap_inner_R")
    for g in GATES:
        post = bb(ns, pose, f"gate_{g}_post_out_R")
        assert leaf.min.X < (post.min.X + post.max.X) / 2 < leaf.max.X          # outer upright stands under the leaf
        assert post.max.Z == pytest.approx(ns["uz"])                            # and touches its underside
    closed = ns["presets"]["closed"]
    pil, pa = bb(ns, closed, "pillar_R"), bb(ns, closed, "flap_outer_R")
    for g in GATES:
        for part in ("post_in", "post_out", "rail", "stretcher"):
            b = bb(ns, closed, f"gate_{g}_{part}_R")
            assert pil.max.X <= b.min.X and b.max.X <= pa.min.X, (g, part)      # between the pillar and the hanging panels


# ---- poses ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("preset", ["open", "one_leaf", "closed"])
def test_every_preset_is_collision_free(ns, preset):
    assert ns["check_pose"](ns["presets"][preset]) == []


def test_a_wrong_pose_is_caught_and_names_the_clashing_parts(ns):
    pose = dict(ns["presets"]["closed"], **{f"gate_{g}_{s}": 0 for g in GATES for s in SIDES})
    assert any(any(n.startswith("gate_") for n in h[:2]) for h in ns["check_pose"](pose))


def steps(n):
    return [i / n for i in range(n + 1)]


def test_the_gates_fold_without_hitting_anything(ns):
    c = ns["presets"]["closed"]
    for f in steps(12):
        pose = {f"gate_{g}_{s}": f * c[f"gate_{g}_{s}"] for g in GATES for s in SIDES}
        assert ns["check_pose"](pose) == [], f"gate fraction {f:.2f}"


def test_the_leaves_fold_after_the_gates(ns):
    c = ns["presets"]["closed"]
    gates = {f"gate_{g}_{s}": c[f"gate_{g}_{s}"] for g in GATES for s in SIDES}
    for f in steps(12):                                  # outer panels fold under the inner ones
        assert ns["check_pose"]({**gates, **{f"flap_outer_{s}": f * 180 for s in SIDES}}) == [], f"outer {f:.2f}"
    for f in steps(12):                                  # then the inner panels hang down
        assert ns["check_pose"]({**gates, **{f"flap_outer_{s}": 180 for s in SIDES}, **{f"flap_inner_{s}": f * 90 for s in SIDES}}) == [], f"inner {f:.2f}"


def test_one_leaf_preset_has_one_side_open_and_one_folded(ns):
    p = ns["presets"]["one_leaf"]
    assert all(p[f"{k}_R"] == 0 for k in ("flap_inner", "flap_outer", "gate_front", "gate_back"))
    assert p["flap_inner_L"] == 90 and p["flap_outer_L"] == 180


def test_mirrored_sides_are_symmetric(ns):
    pose = ns["presets"]["closed"]
    for name in ("flap_inner", "flap_outer", "pillar", "gate_front_post_in", "gate_back_rail"):
        r, l = bb(ns, pose, f"{name}_R"), bb(ns, pose, f"{name}_L")
        assert round(r.min.X + l.max.X, 1) == 0 and round(r.max.X + l.min.X, 1) == 0, name
