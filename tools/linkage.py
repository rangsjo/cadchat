"""Plan-view geometry of a folding zigzag ("W") leg frame.

A chain of links joined by vertical hinges; legs stand at the vertices. Unfolded, the vertices alternate between two sides
(a W seen from above). Each link is `step` mm longer than the previous one, so when the chain is folded like a concertina
(every link parallel to the y axis) the legs stand one `step` apart along the line instead of on top of each other.
"""
import math


def solve_zigzag(x_total, amp, step, n=4):
    """Link x-extents dx_i for n links of lengths L1, L1+step, ... that cross 2*amp in y and cover x_total in x."""
    if step <= 0:
        raise ValueError("step must be positive")
    c = 2.0 * amp
    dx = lambda L: math.sqrt(max(L * L - c * c, 0.0))
    total = lambda L1: sum(dx(L1 + i * step) for i in range(n))
    lo, hi = c, c + x_total + n * step
    if total(lo) > x_total:
        raise ValueError(f"x_total {x_total:g} is too short for {n} links crossing {c:g} mm with a step of {step:g}")
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if total(mid) < x_total else (lo, mid)
    return [dx((lo + hi) / 2 + i * step) for i in range(n)]


def zigzag_vertices(x0, amp, dxs):
    """[(x, y)] with y alternating +amp, -amp, +amp, ... starting at (x0, +amp)."""
    pts, x = [(x0, amp)], x0
    for i, d in enumerate(dxs):
        x += d
        pts.append((x, -amp if i % 2 == 0 else amp))
    return pts


def link_angles(vertices):
    """Direction of each link in degrees (atan2 of dy, dx)."""
    return [math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) for a, b in zip(vertices, vertices[1:])]


def _wrap(a):
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


def fold_angles(vertices):
    """Hinge angles (degrees, counter-clockwise positive, hinge k turns link k and everything beyond it) that lay all
    links along the y axis: link 1 towards -y, link 2 towards +y, and so on."""
    open_dirs, joints, running = link_angles(vertices), [], 0.0
    for k, d in enumerate(open_dirs):
        target = -90.0 if k % 2 == 0 else 90.0
        a = _wrap(target - d - running)
        joints.append(a)
        running += a
    return joints
