"""Plan-view geometry of a folding W (zigzag) leg frame: link lengths, vertices and the fold angles of its vertical hinges."""
import math

import pytest

import linkage


def test_link_lengths_grow_by_the_step_and_reach_the_target(tmp_path):
    dxs = linkage.solve_zigzag(x_total=1300, amp=150, step=70, n=4)
    assert len(dxs) == 4 and sum(dxs) == pytest.approx(1300, abs=0.01)
    lengths = [math.hypot(dx, 300) for dx in dxs]
    assert [round(b - a, 3) for a, b in zip(lengths, lengths[1:])] == [70, 70, 70]


def test_vertices_alternate_between_the_two_sides():
    dxs = linkage.solve_zigzag(1300, 150, 70, 4)
    v = linkage.zigzag_vertices(60, 150, dxs)
    assert [round(y) for _, y in v] == [150, -150, 150, -150, 150]
    assert v[0][0] == 60 and v[-1][0] == pytest.approx(1360, abs=0.01)


def test_impossible_requests_are_rejected():
    with pytest.raises(ValueError):
        linkage.solve_zigzag(x_total=100, amp=150, step=70, n=4)          # too short for the zigzag
    with pytest.raises(ValueError):
        linkage.solve_zigzag(x_total=1300, amp=150, step=-5, n=4)


def fold(vertices, angles):
    """Rotate link k and everything beyond it by angles[k] about vertex k (a chain of vertical hinges)."""
    pts = [list(p) for p in vertices]
    for k, a in enumerate(angles):
        ox, oy = pts[k]
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        for p in pts[k + 1:]:
            x, y = p[0] - ox, p[1] - oy
            p[0], p[1] = ox + c * x - s * y, oy + s * x + c * y
    return pts


def test_fold_angles_stack_all_links_along_one_line():
    v = linkage.zigzag_vertices(60, 150, linkage.solve_zigzag(1300, 150, 70, 4))
    pts = fold(v, linkage.fold_angles(v))
    assert [round(p[0], 6) for p in pts] == [pytest.approx(60, abs=1e-6)] * 5            # all vertices on x = 60
    ys = [p[1] for p in pts]
    assert ys[0] == pytest.approx(150) and ys[1] < ys[0] and ys[2] > ys[0]               # concertina: V2 beyond V0


def test_folded_legs_are_staggered_by_the_link_step():
    v = linkage.zigzag_vertices(60, 150, linkage.solve_zigzag(1300, 150, 70, 4))
    ys = [p[1] for p in fold(v, linkage.fold_angles(v))]
    assert ys[2] - ys[0] == pytest.approx(70, abs=0.01) and ys[4] - ys[2] == pytest.approx(70, abs=0.01)
    assert ys[1] - ys[3] == pytest.approx(70, abs=0.01)                                    # the lower legs are staggered too


def test_fold_angles_are_within_a_half_turn():
    v = linkage.zigzag_vertices(60, 150, linkage.solve_zigzag(1300, 150, 70, 4))
    assert all(-180 <= a <= 180 for a in linkage.fold_angles(v))


def test_link_directions_alternate():
    v = linkage.zigzag_vertices(60, 150, linkage.solve_zigzag(1300, 150, 70, 4))
    dirs = linkage.link_angles(v)
    assert dirs[0] < 0 < dirs[1] and dirs[2] < 0 < dirs[3]
