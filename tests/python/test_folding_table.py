"""Acceptance tests for the example mechanism: a folding drop-leaf table rebuilt from photos and the dealer's sizes.

Reference sizes (dealer listing): folded 23 cm wide, one leaf up 151 cm, fully open 280 cm, 90 cm deep, 73.5 cm high.
Chain of six sheets, left to right: A outer sheet, B base top, C centre sheet, D centre sheet, E base top, F outer sheet.
Hinges: A-B under, B-C under, C-D over, D-E under, E-F under. B and E carry a pillar with two fixed legs and two fold-out legs that
lie flat in the pillar's thickness when folded. The centre sheets C and D fold down into a V (their top faces meet at the V's bottom,
the C-D hinge) while the bases slide together; the slide is coupled to the fold angle. A loose filler sheet fills the gap in the centre.
"""
import math
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
    b = Compound([sh for n, sh in posed(ns, values).items() if not n.startswith("hinge_")]).bounding_box()     # without the brass hardware
    return round(b.size.X), round(b.size.Y), round(b.size.Z)


def joints(ns):
    return {x["name"]: x for x in ns["joints"]}


def cx(ns, values, name):
    b = bb(ns, values, name)
    return (b.min.X + b.max.X) / 2


# ---- structure ------------------------------------------------------------------------------------------------------------------
def test_six_sheets_plus_one_filler(ns):
    names = {p["name"] for p in ns["parts"]}
    assert {f"{k}_{s}" for k in ("outer", "top", "centre") for s in SIDES} <= names
    assert "filler" in names


def test_eight_legs_four_fixed_and_four_fold_out(ns):
    names = [p["name"] for p in ns["parts"]]
    assert sorted(n for n in names if n.startswith("post_")) == sorted(f"post_{g}_{s}" for g in GATES for s in SIDES)
    legs = [n for n in names if n.startswith("gate_") and "_leg_" in n]
    assert len(legs) == 4 and all(f"gate_{g}_stretcher_{s}" in names for g in GATES for s in SIDES)


def test_joint_limits_and_coupling(ns):
    j = joints(ns)
    for s in SIDES:
        assert j[f"fold_{s}"]["max"] == j[f"outer_{s}"]["max"] == 90               # top hinges 90 deg
        assert all(j[f"gate_{g}_{s}"]["max"] == 45 for g in GATES)                 # leg hinge 45 deg
        assert j[f"slide_{s}"]["type"] == "prismatic" and j[f"slide_{s}"]["mimic"]["of"] == f"fold_{s}"


def test_dealer_sizes(ns):
    p = ns["presets"]
    assert 2780 <= size(ns, p["open"])[0] <= 2820                  # 280 cm fully extended
    assert 1490 <= size(ns, p["one_leaf"])[0] <= 1530              # 151 cm: the centre folded, both outer sheets still up
    assert 225 <= size(ns, p["closed"])[0] <= 235                  # 23 cm folded
    for k in ("open", "one_leaf", "closed"):
        x, y, z = size(ns, p[k])
        assert y == 900 and z == 735                               # 90 cm deep, 73.5 cm high


def test_open_top_is_one_flat_surface(ns):
    pose = ns["presets"]["open"]
    for n in ("outer", "top", "centre"):
        for s in SIDES:
            assert bb(ns, pose, f"{n}_{s}").max.Z == pytest.approx(ns["height"], abs=0.01), (n, s)


# ---- the folded stack, hinge sides -----------------------------------------------------------------------------------------------
def test_closed_stack_order_from_left_to_right(ns):
    pose = ns["presets"]["closed"]
    order = ["outer_L", "top_L", "centre_L", "centre_R", "top_R", "outer_R"]
    xs = [cx(ns, pose, n) for n in order]
    assert xs == sorted(xs)
    for name, shape in posed(ns, pose).items():
        b = shape.bounding_box()
        if name != "filler":
            assert -ns["half_c"] - 0.5 <= b.min.X and b.max.X <= ns["half_c"] + 0.5, name


def test_hinges_under_except_the_centre_one_over(ns):
    j = joints(ns)
    for s in SIDES:
        assert j[f"fold_{s}"]["origin"][2] == ns["uz"] and j[f"outer_{s}"]["origin"][2] == ns["uz"]     # A-B, B-C, D-E, E-F under
        assert j[f"fold_{s}"]["parent"] == j[f"outer_{s}"]["parent"] == f"slide_{s}"
    barrel = [p for p in ns["parts"] if p["name"] == "hinge_pin_barrel_R"][0]["shape"].bounding_box()
    assert barrel.max.Z + barrel.min.Z == pytest.approx(2 * ns["height"], abs=0.01)                      # C-D over: pin on the top surface


def test_centre_sheets_form_a_v_whose_hinge_stays_closed_all_the_way(ns):
    for f in range(0, 10):
        ang = f * 10
        pose = {"fold_R": ang, "fold_L": ang}
        r, l = bb(ns, pose, "centre_R"), bb(ns, pose, "centre_L")
        assert r.min.X == pytest.approx(ns["gap"] / 2, abs=0.01) and l.max.X == pytest.approx(-ns["gap"] / 2, abs=0.01), ang


def test_closed_centre_sheets_hang_with_the_top_faces_towards_each_other(ns):
    pose = ns["presets"]["closed"]
    r, l = bb(ns, pose, "centre_R"), bb(ns, pose, "centre_L")
    assert r.min.X == pytest.approx(ns["gap"] / 2, abs=0.01) and r.max.X == pytest.approx(ns["gap"] / 2 + ns["top_t"], abs=0.5)
    assert r.max.Z == pytest.approx(ns["uz"], abs=1.5) and r.min.Z > 0                                  # hangs from the underside pivot


def test_filler_closes_the_gap_between_the_bases_when_dropped_in(ns):
    pose = ns["presets"]["closed"]
    f, tl, tr = bb(ns, pose, "filler"), bb(ns, pose, "top_L"), bb(ns, pose, "top_R")
    assert f.max.Z == pytest.approx(ns["height"], abs=0.01) and f.min.Z == pytest.approx(ns["uz"], abs=0.01)
    assert tl.max.X < f.min.X and f.max.X < tr.min.X and f.min.X - tl.max.X < 3 and tr.min.X - f.max.X < 3


# ---- legs -----------------------------------------------------------------------------------------------------------------------
def test_gates_turn_about_vertical_axes_in_opposite_senses(ns):
    j = joints(ns)
    f, b = j["gate_front_R"], j["gate_back_R"]
    assert f["axis"][:2] == [0, 0] and b["axis"][:2] == [0, 0] and f["axis"][2] == -b["axis"][2] != 0
    assert f["origin"][1] > 0 > b["origin"][1] and f["parent"] == "slide_R"


def test_open_fold_out_legs_stand_under_the_outer_sheet_and_lie_flat_inside_the_pillar_thickness_when_folded(ns):
    pose = ns["presets"]["open"]
    outer = bb(ns, pose, "outer_R")
    pillar_open = bb(ns, pose, "pillar_R")
    for g in GATES:
        leg = bb(ns, pose, f"gate_{g}_leg_R")
        assert outer.min.X < (leg.min.X + leg.max.X) / 2 < outer.max.X                   # the foot stands under the sheet
        assert leg.max.Z == pytest.approx(ns["uz"]) and leg.min.X > pillar_open.max.X    # and well outside the pillar
    closed = ns["presets"]["closed"]
    block = bb(ns, closed, "post_front_R")
    pil = bb(ns, closed, "pillar_R")
    for g in GATES:
        for part in ("leg", "stretcher"):
            b = bb(ns, closed, f"gate_{g}_{part}_R")
            assert block.min.X <= b.min.X and b.max.X <= block.max.X                      # inside the thickness of the pillar block
            assert pil.max.X <= b.min.X                                                   # next to the pillar panel, not in it


# ---- poses ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("preset", ["open", "one_leaf", "closed"])
def test_every_preset_is_collision_free(ns, preset):
    assert ns["check_pose"](ns["presets"][preset]) == []


def test_a_wrong_pose_is_caught_and_names_the_clashing_parts(ns):
    pose = dict(ns["presets"]["closed"], **{f"gate_{g}_{s}": 0 for g in GATES for s in SIDES})        # legs still out
    assert ns["check_pose"](pose)


def steps(n):
    return [i / n for i in range(n + 1)]


def closed_gates(ns, f=1.0):
    return {f"gate_{g}_{s}": f * 45 for g in GATES for s in SIDES}        # 45 = lying flat in the pillar


def test_the_whole_fold_sequence_is_collision_free(ns):
    for f in steps(9):                                   # the fold-out legs lie down
        assert ns["check_pose"](closed_gates(ns, f)) == [], f"gates {f:.2f}"
    flat = closed_gates(ns)
    for f in steps(9):                                   # the outer sheets hang down
        assert ns["check_pose"]({**flat, **{f"outer_{s}": f * 90 for s in SIDES}}) == [], f"outer {f:.2f}"
    base = {**flat, **{f"outer_{s}": 90 for s in SIDES}}
    for f in steps(18):                                  # the centre sheets fold into the V while the bases slide together
        assert ns["check_pose"]({**base, **{f"fold_{s}": f * 90 for s in SIDES}}) == [], f"centre {f:.2f}"


def test_one_leaf_preset_keeps_the_outer_sheets_up_and_folds_the_centre(ns):
    p = ns["presets"]["one_leaf"]
    assert p["fold_R"] == p["fold_L"] == 90 and p["outer_R"] == p["outer_L"] == 0


def test_mirrored_sides_are_symmetric(ns):
    pose = ns["presets"]["closed"]
    for name in ("outer", "top", "centre", "pillar", "post_front", "gate_front_leg", "gate_back_stretcher"):
        r, l = bb(ns, pose, f"{name}_R"), bb(ns, pose, f"{name}_L")
        assert round(r.min.X + l.max.X, 1) == 0 and round(r.max.X + l.min.X, 1) == 0, name
