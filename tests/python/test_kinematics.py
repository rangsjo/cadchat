import pytest
from build123d import Box, Pos

from kinematics import Mechanism, mirrored_joint


def box_at(x, y, z, sx=10, sy=10, sz=10):
    return Pos(x, y, z) * Box(sx, sy, sz)


def lid_mechanism():
    parts = [dict(name="body", shape=box_at(0, 0, 0), joint=None),
             dict(name="lid", shape=box_at(0, 0, 10), joint="hinge")]       # sits on top of the body
    joints = [dict(name="hinge", label="Hinge", group="g", parent=None, origin=[-5, 0, 5], axis=[0, -1, 0], min=0, max=180)]
    return Mechanism(parts, joints, {"closed": {"hinge": 0}, "open": {"hinge": 90}})


def bbox(m, values, name):
    return dict(m.posed(values))[name].bounding_box()


def test_zero_angle_leaves_geometry_unchanged():
    m = lid_mechanism()
    bb = bbox(m, {}, "lid")
    assert (round(bb.min.Z), round(bb.max.Z)) == (5, 15)


def test_hinge_rotates_the_lid_about_its_axis():
    bb = bbox(lid_mechanism(), {"hinge": 90}, "lid")
    # axis -Y: +90 stands the lid up on the left edge of the body
    assert (round(bb.min.X), round(bb.max.X)) == (-15, -5)
    assert (round(bb.min.Z), round(bb.max.Z)) == (5, 15)


def test_child_joint_follows_its_parent():
    parts = [dict(name="a", shape=box_at(0, 0, 0), joint="j1"), dict(name="b", shape=box_at(20, 0, 0), joint="j2")]
    joints = [dict(name="j1", label="1", group="g", parent=None, origin=[0, 0, 0], axis=[0, 0, 1], min=0, max=180),
              dict(name="j2", label="2", group="g", parent="j1", origin=[20, 0, 0], axis=[0, 0, 1], min=0, max=180)]
    m = Mechanism(parts, joints, {"d": {}})
    bb = bbox(m, {"j1": 90}, "b")        # parent turns everything 90 deg about z: x=20 -> y=20
    assert round((bb.min.Y + bb.max.Y) / 2) == 20 and round((bb.min.X + bb.max.X) / 2) == 0


def test_mirrored_joint_flips_x_and_axial_components():
    j = dict(name="f_R", label="Hinge (R)", group="g", parent=None, origin=[5, 3, 2], axis=[0, 1, 0], min=0, max=90)
    mj = mirrored_joint(j, "L")
    assert mj["name"] == "f_L" and mj["origin"] == [-5, 3, 2] and mj["axis"] == [0, -1, 0]


def test_mirrored_joint_keeps_parent_pairing():
    j = dict(name="o_R", label="x", group="g", parent="i_R", origin=[1, 0, 0], axis=[0, 0, 1], min=0, max=90)
    assert mirrored_joint(j, "L")["parent"] == "i_L" and mirrored_joint(j, "L")["axis"] == [0, 0, -1]


def test_check_reports_overlap_and_names_the_pair():
    m = lid_mechanism()
    assert m.check({"hinge": 0}) == []                              # lid just touches the body
    hits = m.check({"hinge": -90})                                  # swung the wrong way, into the body
    assert hits and sorted(hits[0][:2]) == ["body", "lid"] and hits[0][2] > 1


def test_exempt_pairs_are_not_reported():
    m = lid_mechanism()
    m.exempt = lambda a, b: {a, b} == {"body", "lid"}
    assert m.check({"hinge": -90}) == []


def test_presets_fill_missing_joints_with_zero():
    m = lid_mechanism()
    assert m.presets["closed"] == {"hinge": 0} and m.presets["open"] == {"hinge": 90}


def test_unknown_joint_value_is_rejected():
    with pytest.raises(KeyError):
        lid_mechanism().posed({"nope": 10})


# ---- speed: pairs that move together are computed once ---------------------------------------------------------------
def three_part_mechanism(cache=True):
    parts = [dict(name="body", shape=box_at(0, 0, 0), joint=None),
             dict(name="rib", shape=box_at(4, 0, 0), joint=None),                  # overlaps the body, never moves
             dict(name="lid", shape=box_at(0, 0, 10), joint="hinge")]
    joints = [dict(name="hinge", label="Hinge", group="g", parent=None, origin=[-5, 0, 5], axis=[0, -1, 0], min=0, max=180)]
    return Mechanism(parts, joints, {"d": {}}, cache=cache)


def test_pairs_that_do_not_move_relative_to_each_other_are_computed_once():
    m = three_part_mechanism()
    m.check({})
    first = m.stats["boolean_calls"]
    m.check({"hinge": 30})
    m.check({"hinge": 60})
    # body/rib is rigid in every pose: only the pairs involving the lid are recomputed
    assert m.stats["boolean_calls"] - first <= 2 * (first - 1)


def test_cached_and_uncached_checks_agree_in_every_pose():
    a, b = three_part_mechanism(cache=True), three_part_mechanism(cache=False)
    for angle in (0, 15, 45, 90, -45, -90, 120):
        assert a.check({"hinge": angle}) == b.check({"hinge": angle}), angle


def test_rigid_overlap_is_still_reported_from_the_cache():
    m = three_part_mechanism()
    for angle in (0, 30):
        assert any(sorted(h[:2]) == ["body", "rib"] for h in m.check({"hinge": angle}))


def slide_mechanism():
    parts = [dict(name="rail", shape=box_at(0, 0, 0), joint=None),
             dict(name="car", shape=box_at(0, 0, 10), joint="slide"),
             dict(name="lid", shape=box_at(0, 0, 20), joint="hinge")]
    joints = [dict(name="slide", label="Slide", group="g", type="prismatic", parent=None, origin=[0, 0, 0], axis=[1, 0, 0], min=0, max=100),
              dict(name="hinge", label="Hinge", group="g", parent="slide", origin=[-5, 0, 15], axis=[0, -1, 0], min=0, max=90)]
    return Mechanism(parts, joints, {"out": {"slide": 50}})


def test_prismatic_joint_translates_along_its_axis_in_mm():
    bb = bbox(slide_mechanism(), {"slide": 50}, "car")
    assert (round(bb.min.X), round(bb.max.X)) == (45, 55)


def test_revolute_child_of_a_prismatic_joint_is_carried_along():
    bb = bbox(slide_mechanism(), {"slide": 50, "hinge": 90}, "lid")
    assert (round(bb.min.X), round(bb.max.X)) == (35, 45)


def test_mirrored_prismatic_joint_moves_the_opposite_way():
    j = dict(name="slide_R", label="Slide (R)", group="g", type="prismatic", parent=None, origin=[0, 0, 0], axis=[-1, 0, 0], min=0, max=10)
    m = mirrored_joint(j, "L")
    assert m["type"] == "prismatic" and m["axis"] == [1, 0, 0] and m["name"] == "slide_L"


def test_posing_twice_does_not_move_the_reference_shapes():
    m = slide_mechanism()
    first = bbox(m, {"slide": 50}, "car").min.X
    assert bbox(m, {"slide": 50}, "car").min.X == first
    assert round(bbox(m, {}, "car").min.X) == -5
