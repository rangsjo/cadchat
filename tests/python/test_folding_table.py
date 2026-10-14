"""Acceptance tests for the example mechanism: a folding drop-leaf table rebuilt from photos and the dealer's sizes.

Reference sizes (dealer listing): folded 23 cm wide, one leaf up 151 cm, fully open 280 cm, 90 cm deep, 73.5 cm high.
Structure: two bases (a pillar under a cap) that slide together. Per side six sheets in all: a centre sheet hinged on the inner edge of
the cap, a middle sheet on the outer edge and an outer sheet folding under the middle one, plus one small filler sheet in the centre
that closes the gap when both centre sheets hang down. Each base carries on each side an N-shaped leg frame (two legs and a diagonal)
that swings out on a vertical hinge, 45 deg at most: 4 frames, 8 legs. Top hinges open to 90 deg.
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


def joints(ns):
    return {x["name"]: x for x in ns["joints"]}


# ---- structure ------------------------------------------------------------------------------------------------------------------
def test_six_sheets_plus_one_filler(ns):
    names = {p["name"] for p in ns["parts"]}
    sheets = {n for n in names if n.split("_")[0] in ("centre", "middle", "outer") and n.endswith(("_R", "_L"))}
    assert sheets == {f"{k}_{s}" for k in ("centre", "middle", "outer") for s in SIDES}
    assert "filler" in names


def test_eight_legs_in_four_n_frames(ns):
    legs = [p["name"] for p in ns["parts"] if "_leg_" in p["name"]]
    assert len(legs) == 8
    frames = {n.split("_leg_")[0] + n[-2:] for n in legs}
    assert len(frames) == 4
    assert all(f"{f[:-2]}_brace{f[-2:]}" in {p["name"] for p in ns["parts"]} for f in frames)


def test_joint_limits(ns):
    j = joints(ns)
    assert j["slide_R"]["type"] == "prismatic" and j["slide_R"]["min"] == 0 and j["slide_R"]["max"] > 300
    for s in SIDES:
        assert j[f"centre_{s}"]["max"] == j[f"middle_{s}"]["max"] == 90          # top hinge 90 deg
        assert all(j[f"gate_{g}_{s}"]["max"] == 45 for g in GATES)               # leg hinge 45 deg


def test_dealer_sizes(ns):
    p = ns["presets"]
    assert 2780 <= size(ns, p["open"])[0] <= 2820                  # 280 cm fully extended
    assert 1490 <= size(ns, p["one_leaf"])[0] <= 1530              # 151 cm with one leaf up
    assert 225 <= size(ns, p["closed"])[0] <= 235                  # 23 cm folded
    for k in ("open", "one_leaf", "closed"):
        x, y, z = size(ns, p[k])
        assert y == 900 and z == 735                               # 90 cm deep, 73.5 cm high


def test_open_top_is_one_flat_surface(ns):
    pose = ns["presets"]["open"]
    names = ["centre", "middle", "outer"]
    for n in names:
        for s in SIDES:
            b = bb(ns, pose, f"{n}_{s}")
            assert b.max.Z == pytest.approx(ns["height"], abs=0.01), (n, s)
    assert bb(ns, pose, "filler").max.Z == pytest.approx(ns["height"], abs=0.01)


def test_closed_everything_is_inside_the_footprint_of_the_caps(ns):
    pose = ns["presets"]["closed"]
    for name, shape in posed(ns, pose).items():
        b = shape.bounding_box()
        assert -ns["half_c"] - 0.5 <= b.min.X and b.max.X <= ns["half_c"] + 0.5, name


def test_filler_closes_the_gap_between_the_hanging_centre_sheets(ns):
    pose = ns["presets"]["closed"]
    f, r, l = bb(ns, pose, "filler"), bb(ns, pose, "centre_R"), bb(ns, pose, "centre_L")
    assert l.max.X < f.min.X + 20 and f.max.X > r.min.X - 20                  # the gap is small enough for the filler
    assert r.min.X - l.max.X > f.size.X                                       # but not closed: the filler is an extra sheet


# ---- hinges ---------------------------------------------------------------------------------------------------------------------
def test_top_hinges_sit_in_the_top_skin_and_the_under_hinge_on_the_underside(ns):
    j = joints(ns)
    for s in SIDES:
        assert j[f"centre_{s}"]["origin"][2] > ns["uz"] and j[f"middle_{s}"]["origin"][2] > ns["uz"]
        assert j[f"outer_{s}"]["origin"][2] == ns["uz"] and j[f"outer_{s}"]["parent"] == f"middle_{s}"
        assert j[f"centre_{s}"]["parent"] == j[f"middle_{s}"]["parent"] == f"slide_{s}"


def test_gates_turn_about_vertical_axes_in_opposite_senses(ns):
    j = joints(ns)
    f, b = j["gate_front_R"], j["gate_back_R"]
    assert f["axis"][:2] == [0, 0] and b["axis"][:2] == [0, 0] and f["axis"][2] == -b["axis"][2] != 0
    assert f["origin"][1] > 0 > b["origin"][1] and f["parent"] == "slide_R"


def test_open_n_frames_stand_at_45_deg_under_the_middle_sheet_and_lie_flat_when_folded(ns):
    pose = ns["presets"]["open"]
    mid = bb(ns, pose, "middle_R")
    for g in GATES:
        leg = bb(ns, pose, f"gate_{g}_leg_out_R")
        assert mid.min.X < (leg.min.X + leg.max.X) / 2 < mid.max.X            # the free leg stands under the sheet
        assert leg.max.Z == pytest.approx(ns["uz"])                           # and touches its underside
    closed = ns["presets"]["closed"]
    pil, hang = bb(ns, closed, "pillar_R"), bb(ns, closed, "outer_R")
    for g in GATES:
        for part in ("leg_in", "leg_out", "brace"):
            b = bb(ns, closed, f"gate_{g}_{part}_R")
            assert pil.max.X <= b.min.X and b.max.X <= hang.min.X, (g, part)  # between the pillar and the hanging sheets


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
    for f in steps(9):
        pose = {f"gate_{g}_{s}": f * c[f"gate_{g}_{s}"] for g in GATES for s in SIDES}
        assert ns["check_pose"](pose) == [], f"gate fraction {f:.2f}"


def fold_all(c, f=1.0, **extra):
    gates = {f"gate_{g}_{s}": c[f"gate_{g}_{s}"] for g in GATES for s in SIDES}
    return {**gates, **extra}


def test_sheets_fold_then_the_halves_slide_together(ns):
    c = ns["presets"]["closed"]
    for f in steps(8):                                   # outer sheets fold under the middle ones
        assert ns["check_pose"](fold_all(c, **{f"outer_{s}": f * 180 for s in SIDES})) == [], f"outer {f:.2f}"
    base = fold_all(c, **{f"outer_{s}": 180 for s in SIDES})
    for f in steps(8):                                   # then the middle sheets hang down
        assert ns["check_pose"]({**base, **{f"middle_{s}": f * 90 for s in SIDES}}) == [], f"middle {f:.2f}"
    base = {**base, **{f"middle_{s}": 90 for s in SIDES}}
    for f in steps(8):                                   # and the centre sheets
        assert ns["check_pose"]({**base, **{f"centre_{s}": f * 90 for s in SIDES}}) == [], f"centre {f:.2f}"
    base = {**base, **{f"centre_{s}": 90 for s in SIDES}}
    for f in steps(8):                                   # the halves slide together
        assert ns["check_pose"]({**base, **{f"slide_{s}": f * c[f"slide_{s}"] for s in SIDES}}) == [], f"slide {f:.2f}"


def test_one_leaf_preset_has_one_side_open_and_one_folded(ns):
    p = ns["presets"]["one_leaf"]
    assert all(p[f"{k}_R"] == 0 for k in ("slide", "centre", "middle", "outer", "gate_front", "gate_back"))
    assert p["centre_L"] == p["middle_L"] == 90 and p["outer_L"] == 180 and p["slide_L"] == joints(ns)["slide_L"]["max"]


def test_mirrored_sides_are_symmetric(ns):
    pose = ns["presets"]["closed"]
    for name in ("centre", "middle", "outer", "pillar", "gate_front_leg_in", "gate_back_brace"):
        r, l = bb(ns, pose, f"{name}_R"), bb(ns, pose, f"{name}_L")
        assert round(r.min.X + l.max.X, 1) == 0 and round(r.max.X + l.min.X, 1) == 0, name
