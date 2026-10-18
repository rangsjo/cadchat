"""Woodworking joints between axis-aligned boards: each joint returns both boards cut to fit (plus hardware such as dowels), the
parameters it used and a note for the cut list. Boards must not overlap afterwards; the cuts must have the textbook size."""
import math

import pytest
from build123d import Box, Pos

import joints


def board(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def vol(s):
    return sum(x.volume for x in s.solids())


def overlap(a, b):
    i = a.intersect(b)
    return vol(i) if i else 0.0


# ---- helpers ---------------------------------------------------------------------------------------------------------------------
def test_defaults_follow_the_usual_proportions_of_the_thickness():
    d = joints.defaults("mortise_tenon", 18)
    assert d["tenon_t"] == pytest.approx(6) and d["tenon_len"] == pytest.approx(27)            # 1/3 and 1.5 x the thickness
    assert joints.defaults("dado", 18)["depth"] == pytest.approx(6)                            # 1/3
    assert joints.defaults("half_lap", 18)["depth"] == pytest.approx(9)                        # 1/2
    assert joints.defaults("dowel_butt", 18)["dia"] == pytest.approx(6) and joints.defaults("dowel_butt", 18)["depth"] == pytest.approx(18 * 0.6, abs=0.5)
    with pytest.raises(KeyError):
        joints.defaults("glue", 18)


# ---- dowel butt joint -----------------------------------------------------------------------------------------------------------
def dowel_case():
    top = board(0, 400, 0, 200, 18, 36)                         # top board lying on ...
    side = board(0, 400, 0, 200, 0, 18)                         # ... a board below it (face to face in z)
    return top, side


def test_dowel_butt_drills_both_boards_and_returns_loose_dowels():
    a, b = dowel_case()
    j = joints.dowel_butt(a, b, dia=8, count=3, depth=15, edge=40, clearance=0.1)
    hole = math.pi * 4.1 ** 2 * 15
    assert vol(a) - vol(j.a) == pytest.approx(3 * hole, rel=0.02) and vol(b) - vol(j.b) == pytest.approx(3 * hole, rel=0.02)
    assert len(j.hardware) == 3 and all(n.startswith("dowel") for n, _ in j.hardware)
    for _, d in j.hardware:
        assert overlap(d, j.a) < 1 and overlap(d, j.b) < 1                                      # loose in the holes
        bb = d.bounding_box()
        assert bb.min.Z > 18 - 15 and bb.max.Z < 18 + 15                                        # spans the joint line
    assert "dowel" in j.notes[0].lower() and "8" in j.notes[0]


def test_dowels_are_spread_along_the_long_side_with_the_edge_distance():
    a, b = dowel_case()
    j = joints.dowel_butt(a, b, dia=8, count=3, depth=15, edge=40)
    xs = sorted(round(d.bounding_box().center().X) for _, d in j.hardware)
    ys = {round(d.bounding_box().center().Y) for _, d in j.hardware}
    assert xs == [40, 200, 360] and ys == {100}


def test_dowel_butt_needs_boards_that_touch_face_to_face():
    a, _ = dowel_case()
    far = board(0, 400, 0, 200, -50, -32)
    with pytest.raises(ValueError):
        joints.dowel_butt(a, far)


# ---- dado, rabbet (housing joints) ------------------------------------------------------------------------------------------
def dado_case():
    side = board(0, 18, 0, 300, 0, 700)                                  # vertical side panel
    shelf = board(12, 400, 0, 300, 300, 318)                             # shelf end sits 6 mm into the side
    return side, shelf


def test_dado_cuts_a_groove_of_the_shelf_size_into_the_panel():
    side, shelf = dado_case()
    j = joints.dado(side, shelf, clearance=0.0)
    assert vol(side) - vol(j.a) == pytest.approx(6 * 18 * 300, rel=0.001)         # depth x shelf thickness x shelf width
    assert vol(j.b) == pytest.approx(vol(shelf)) and overlap(j.a, j.b) < 1
    assert "dado" in j.notes[0].lower()


def test_dado_clearance_widens_the_groove_in_thickness_and_depth():
    side, shelf = dado_case()
    j = joints.dado(side, shelf, clearance=0.2)
    assert vol(side) - vol(j.a) > 6 * 18 * 300 and overlap(j.a, j.b) < 1


def test_through_dado_runs_out_at_the_panel_edges():
    side = board(0, 18, 0, 400, 0, 700)
    shelf = board(12, 400, 20, 380, 300, 318)                            # narrower than the panel
    stopped = joints.dado(side, shelf, clearance=0.0)
    through = joints.dado(side, shelf, clearance=0.0, through=True)
    assert vol(side) - vol(stopped.a) == pytest.approx(6 * 18 * 360, rel=0.001)
    assert vol(side) - vol(through.a) == pytest.approx(6 * 18 * 400, rel=0.001)


def test_rabbet_notches_the_edge_of_a_board_for_another_board():
    case = board(0, 600, 0, 18, 0, 800)                                   # side of a case
    back = board(0, 600, 12, 18, 0, 800)                                  # 6 mm back, in the rabbet of the rear edge
    j = joints.rabbet(case, back, clearance=0.0)
    assert vol(case) - vol(j.a) == pytest.approx(6 * 600 * 800, rel=0.001) and overlap(j.a, j.b) < 1
    assert "rabbet" in j.notes[0].lower()


# ---- half lap ---------------------------------------------------------------------------------------------------------------------
def test_half_lap_removes_half_the_thickness_from_each_board_and_they_interlock():
    a = board(0, 300, 40, 80, 0, 20)                                     # crossing rails, same layer
    b = board(100, 140, 0, 200, 0, 20)
    j = joints.half_lap(a, b, a_on_top=True)
    o = 40 * 40 * 20
    assert vol(a) - vol(j.a) == pytest.approx(o / 2, rel=0.001) and vol(b) - vol(j.b) == pytest.approx(o / 2, rel=0.001)
    assert overlap(j.a, j.b) < 1
    assert vol(j.a.fuse(j.b)) == pytest.approx(vol(a.fuse(b)), rel=0.001)    # same silhouette as the two crossing boards
    top = j.a.intersect(board(100, 140, 40, 80, 10, 20))
    assert vol(top) == pytest.approx(40 * 40 * 10, rel=0.001)                # a keeps the upper half at the crossing


# ---- mortise and tenon ---------------------------------------------------------------------------------------------------------
def mt_case():
    stile = board(0, 45, 0, 45, 0, 700)                                   # leg
    rail = board(20, 320, 10, 35, 100, 190)                               # rail whose end enters the leg by 25 mm (x 20..45)
    return stile, rail


def test_tenon_is_a_third_of_the_rail_thickness_and_fits_a_mortise_in_the_stile():
    stile, rail = mt_case()
    j = joints.mortise_tenon(rail, stile, axis="x", tenon_len=25, shoulder=10, clearance=0.0)
    tenon = 25 * (25 / 3) * (90 - 20)                                     # length x thickness (1/3 of 25) x width (rail height 90 less 2 shoulders)
    assert vol(rail) - vol(j.a) == pytest.approx(25 * 25 * 90 - tenon, rel=0.001)       # the cheeks and shoulders inside the stile are gone
    assert vol(stile) - vol(j.b) == pytest.approx(tenon, rel=0.001)                      # mortise = tenon
    assert overlap(j.a, j.b) < 1
    assert "mortise" in j.notes[0].lower() and "tenon" in j.notes[0].lower()


def test_mortise_has_glue_clearance_around_the_tenon():
    stile, rail = mt_case()
    tight = joints.mortise_tenon(rail, stile, axis="x", tenon_len=25, clearance=0.0)
    loose = joints.mortise_tenon(rail, stile, axis="x", tenon_len=25, clearance=0.15)
    assert vol(stile) - vol(loose.b) > vol(stile) - vol(tight.b) and overlap(loose.a, loose.b) < 1


def test_tenon_defaults_come_from_the_rail():
    stile, rail = mt_case()
    j = joints.mortise_tenon(rail, stile, axis="x", clearance=0.0)         # tenon length = how far the rail enters the stile
    assert j.params["tenon_t"] == pytest.approx(25 / 3) and j.params["tenon_len"] == pytest.approx(25)


def test_a_joint_needs_the_boards_to_overlap():
    stile = board(0, 45, 0, 45, 0, 700)
    rail = board(60, 320, 10, 35, 100, 190)
    with pytest.raises(ValueError):
        joints.mortise_tenon(rail, stile, axis="x")


def test_a_joint_describes_itself_for_the_viewer_constraint_list():
    stile, rail = mt_case()
    j = joints.mortise_tenon(rail, stile, axis="x", tenon_len=25)
    c = j.as_constraint("leg_rail", "rail", "leg")
    assert c["kind"] == "fixed" and c["a"] == "rail" and c["b"] == "leg" and c["id"] == "leg_rail" and "tenon" in c["expr"].lower()
