"""Acceptance tests for the example mechanism.

The design (from the user's review): the legs form a "W" seen from above, four links joined by vertical hinges with a leg at every
vertex and the last leg under the outermost table top; the links interleave (different heights, alternating sides) and fold like a
concertina; the outer flaps are hinged on the TOP side so they fold the other way than the inner ones (inner flaps hang down, outer
flaps fold over them).
"""
import runpy
from pathlib import Path

import pytest
from build123d import Compound

SCRIPT = Path(__file__).resolve().parents[2] / "parts" / "folding_table.py"
SIDES = "RL"
LINKS = (1, 2, 3, 4)


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


def test_structure(ns):
    assert len(ns["joints"]) == 12 and len(ns["parts"]) == 43
    assert set(ns["presets"]) == {"open", "half", "closed"}
    assert all(p["role"] for p in ns["parts"]) and all(p["material"] for p in ns["parts"])


def test_w_hinges_are_vertical_and_chained(ns):
    j = {x["name"]: x for x in ns["joints"]}
    for s in SIDES:
        for k in LINKS:
            h = j[f"arm_{k}_{s}"]
            assert h["axis"][:2] == [0, 0] and abs(h["axis"][2]) == 1
            assert h["parent"] == (f"arm_{k - 1}_{s}" if k > 1 else None)


def test_outer_hinge_is_on_the_top_side_inner_hinge_on_the_underside(ns):
    j = {x["name"]: x for x in ns["joints"]}
    assert j["flap_inner_R"]["origin"][2] == ns["uz"] and j["flap_outer_R"]["origin"][2] == ns["height"]


def test_open_size_is_centre_plus_four_flaps(ns):
    x, y, z = size(ns, ns["presets"]["open"])
    assert (x, y) == (2834, 900) and 720 <= z <= 725          # the hinge barrel and leaves on the top side stand up to 4 mm proud


def test_open_legs_form_a_w_seen_from_above(ns):
    pose = ns["presets"]["open"]
    centres = []
    for name in ["post_R"] + [f"leg_{k}_R" for k in LINKS]:
        b = bb(ns, pose, name)
        centres.append(((b.min.X + b.max.X) / 2, (b.min.Y + b.max.Y) / 2))
    ys = [y for _, y in centres]
    assert all(a * b < 0 for a, b in zip(ys, ys[1:])), "y must alternate sign: W shape"
    assert [round(abs(y)) for y in ys] == [round(ns["V"]["leg_amp"])] * 5
    xs = [x for x, _ in centres]
    assert xs == sorted(xs)


def test_open_last_leg_is_under_the_very_last_table_top(ns):
    pose = ns["presets"]["open"]
    outer, foot = bb(ns, pose, "flap_outer_R"), bb(ns, pose, "leg_4_R")
    assert outer.min.X < (foot.min.X + foot.max.X) / 2 < outer.max.X
    assert foot.min.Z == pytest.approx(0) and foot.max.Z == pytest.approx(ns["uz"])
    for k in (1, 2):                                   # and the inner flap has legs below it too
        inner = bb(ns, pose, "flap_inner_R")
        leg = bb(ns, pose, f"leg_{k}_R")
        assert inner.min.X < (leg.min.X + leg.max.X) / 2 < inner.max.X


def test_closed_is_a_slim_slab_with_all_legs_under_the_centre_top(ns):
    pose = ns["presets"]["closed"]
    x, y, z = size(ns, pose)
    assert x < 345 and y == 900 and 720 <= z <= 725
    centre = bb(ns, pose, "centre_top")
    for name, shape in posed(ns, pose).items():
        if name.startswith(("post_", "leg_", "arm_rail_", "stretcher_")):
            b = shape.bounding_box()
            assert centre.min.X - 1 <= b.min.X and b.max.X <= centre.max.X + 1, name


def test_closed_outer_flap_lies_outside_the_hanging_inner_flap(ns):
    pose = ns["presets"]["closed"]
    inner, outer = bb(ns, pose, "flap_inner_R"), bb(ns, pose, "flap_outer_R")
    assert outer.min.X >= inner.max.X - 0.5 and outer.max.X - outer.min.X == pytest.approx(25, abs=1)


def test_half_stacks_the_outer_flaps_on_top_of_the_inner_ones(ns):
    pose = ns["presets"]["half"]
    inner, outer = bb(ns, pose, "flap_inner_R"), bb(ns, pose, "flap_outer_R")
    assert outer.min.Z >= inner.max.Z - 0.5 and inner.min.X - 1 < outer.min.X and outer.max.X < inner.max.X + 60


@pytest.mark.parametrize("preset", ["open", "half", "closed"])
def test_every_preset_is_collision_free(ns, preset):
    assert ns["check_pose"](ns["presets"][preset]) == []


def test_a_wrong_pose_is_caught_and_names_the_clashing_parts(ns):
    pose = dict(ns["presets"]["closed"], **{f"arm_{k}_{s}": 0 for k in LINKS for s in SIDES})
    hits = ns["check_pose"](pose)
    assert any("flap_inner_R" in h[:2] for h in hits)


def legs_at(ns, f):
    """All W hinges at fraction f of their closed angle."""
    closed = ns["presets"]["closed"]
    return {f"arm_{k}_{s}": f * closed[f"arm_{k}_{s}"] for k in LINKS for s in SIDES}


def test_the_legs_can_fold_without_hitting_each_other(ns):
    for i in range(0, 13):
        f = i / 12
        assert ns["check_pose"](legs_at(ns, f)) == [], f"fraction {f:.2f}"


def test_the_flaps_can_fold_after_the_legs(ns):
    folded = legs_at(ns, 1)
    for i in range(0, 13):                            # outer flaps over the inner ones
        o = 180 * i / 12
        assert ns["check_pose"]({**folded, **{f"flap_outer_{s}": o for s in SIDES}}) == [], f"outer {o}"
    for i in range(0, 10):                            # then the inner flaps down
        a = 90 * i / 9
        assert ns["check_pose"]({**folded, **{f"flap_outer_{s}": 180 for s in SIDES}, **{f"flap_inner_{s}": a for s in SIDES}}) == [], f"inner {a}"


def test_mirrored_sides_are_symmetric(ns):
    pose = ns["presets"]["closed"]
    for name in ("flap_inner", "leg_1", "leg_4", "arm_rail_2"):
        r, l = bb(ns, pose, f"{name}_R"), bb(ns, pose, f"{name}_L")
        assert round(r.min.X + l.max.X, 1) == 0 and round(r.max.X + l.min.X, 1) == 0, name
