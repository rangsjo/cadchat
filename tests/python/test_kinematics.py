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
