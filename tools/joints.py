"""Woodworking joints between axis-aligned boards (build123d solids).

Each joint takes the boards in their final position, overlapping where one goes into the other (a shelf end 6 mm into a side, a rail end
25 mm into a leg, two crossing rails), and returns a Joint: both boards cut to fit, loose hardware (dowels), the parameters used and a
note for the cut list. `defaults(kind, thickness)` gives the usual proportions, so a joint can be asked for with no numbers at all.

Boards must be boxes aligned with the axes (the usual case for furniture; build a rotated joint in place, then rotate the result).
Clearance is the glue gap: it is added only where it lies inside the board that is cut, never outside it.
"""
import math
from dataclasses import dataclass, field

from build123d import Box, Cylinder, Pos, Rot

AXES = {"x": 0, "y": 1, "z": 2}
TOL = 1e-6


@dataclass
class Joint:
    kind: str
    a: object
    b: object
    hardware: list = field(default_factory=list)       # [(name, shape)] loose parts: dowels, ...
    params: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)           # lines for the cut list

    def as_constraint(self, cid, a_name, b_name):
        """An entry for the `constraints` list of publish_kinematic: shows the joint and its numbers in the viewer."""
        return dict(id=cid, kind="fixed", label=f"{self.kind.replace('_', ' ').capitalize()} joint: {a_name} - {b_name}", a=a_name, b=b_name,
                    parts=[a_name, b_name], params=[], expr=self.notes[0] if self.notes else self.kind)


# ---- box helpers -----------------------------------------------------------------------------------------------------------------
def _bounds(shape):
    bb = shape.bounding_box()
    return [bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]


def _box(lo, hi):
    return Pos(*[(l + h) / 2 for l, h in zip(lo, hi)]) * Box(*[h - l for l, h in zip(lo, hi)])


def _overlap(a, b):
    la, ha = _bounds(a)
    lb, hb = _bounds(b)
    lo, hi = [max(x, y) for x, y in zip(la, lb)], [min(x, y) for x, y in zip(ha, hb)]
    if any(h - l <= TOL for l, h in zip(lo, hi)):
        raise ValueError("the boards do not overlap: put the joining part into the other one by the depth of the joint")
    return lo, hi


def _cut(shape, lo, hi):
    return shape - _box(lo, hi)


def _axis(axis):
    try:
        return AXES[axis]
    except KeyError:
        raise ValueError("axis must be 'x', 'y' or 'z'") from None


def defaults(kind, thickness):
    """Textbook proportions for boards of the given thickness (mm)."""
    t = float(thickness)
    table = {
        "mortise_tenon": dict(tenon_t=t / 3, tenon_len=1.5 * t, shoulder=t / 3),
        "dado": dict(depth=t / 3),
        "rabbet": dict(depth=t / 2),
        "half_lap": dict(depth=t / 2),
        "dowel_butt": dict(dia=t / 3, depth=0.6 * t, count=2, edge=max(2.5 * t / 3, 25.0)),
    }
    return dict(table[kind])


# ---- housing joints: dado, rabbet ------------------------------------------------------------------------------------------------
def _housing(host, guest, clearance, through=False):
    """Cut `host` where `guest` enters it. The cut is widened by `clearance` only on faces that lie inside the host."""
    lo, hi = _overlap(host, guest)
    hl, hh = _bounds(host)
    gl, gh = _bounds(guest)
    pen = [i for i in range(3) if gl[i] < lo[i] - TOL or gh[i] > hi[i] + TOL]            # axes along which the guest sticks out
    if through:
        cross = [i for i in range(3) if i not in pen]
        i = max(cross, key=lambda k: hi[k] - lo[k])                                       # the width of the guest
        lo[i], hi[i] = hl[i], hh[i]
    cl, ch = list(lo), list(hi)
    for i in range(3):
        if lo[i] > hl[i] + TOL:
            cl[i] = lo[i] - clearance
        if hi[i] < hh[i] - TOL:
            ch[i] = hi[i] + clearance
    return _cut(host, cl, ch), lo, hi


def dado(panel, shelf, clearance=0.2, through=False):
    """A groove in `panel` that takes the end of `shelf` (the shelf overlaps the panel by the groove depth). through=True runs the
    groove out at both edges of the panel instead of stopping at the ends of the shelf."""
    new, lo, hi = _housing(panel, shelf, clearance, through)
    depth = min(hi[i] - lo[i] for i in range(3))
    width = max(hi[i] - lo[i] for i in range(3))
    return Joint("dado", new, shelf, params=dict(depth=depth, clearance=clearance, through=through),
                 notes=[f"Dado {depth:.1f} mm deep for a {min(sorted(h - l for l, h in zip(lo, hi))[1:]):.1f} mm board, {'through' if through else 'stopped'}"
                        f" (groove width {width:.0f} mm)"])


def rabbet(host, guest, clearance=0.2):
    """A step along the edge of `host` that takes `guest` (a back panel, a drawer bottom)."""
    new, lo, hi = _housing(host, guest, clearance)
    ext = sorted(h - l for l, h in zip(lo, hi))
    return Joint("rabbet", new, guest, params=dict(depth=ext[0], clearance=clearance),
                 notes=[f"Rabbet {ext[0]:.1f} mm deep along {ext[2]:.0f} mm"])


# ---- half lap ---------------------------------------------------------------------------------------------------------------------
def half_lap(a, b, a_on_top=True, axis=None, clearance=0.0):
    """Two boards crossing in the same layer, each cut away by half the thickness so they interlock flush. axis = the thickness
    direction (default: the one in which both boards are fully overlapped and thinnest). a keeps the upper half when a_on_top."""
    lo, hi = _overlap(a, b)
    la, ha = _bounds(a)
    lb, hb = _bounds(b)
    if axis is None:
        full = [i for i in range(3) if abs(ha[i] - la[i] - (hi[i] - lo[i])) < 1e-3 and abs(hb[i] - lb[i] - (hi[i] - lo[i])) < 1e-3]
        if not full:
            raise ValueError("boards in different layers: a half lap needs both boards to have the same thickness")
        i = min(full, key=lambda k: hi[k] - lo[k])
    else:
        i = _axis(axis)
    mid = (lo[i] + hi[i]) / 2
    ca_lo, ca_hi = list(lo), list(hi)           # a_on_top: a loses the lower half, b the upper half
    cb_lo, cb_hi = list(lo), list(hi)
    if a_on_top:
        ca_hi[i] = mid + clearance / 2
        cb_lo[i] = mid - clearance / 2
    else:
        ca_lo[i] = mid - clearance / 2
        cb_hi[i] = mid + clearance / 2
    d = (hi[i] - lo[i]) / 2
    return Joint("half_lap", _cut(a, ca_lo, ca_hi), _cut(b, cb_lo, cb_hi), params=dict(depth=d, clearance=clearance),
                 notes=[f"Half lap {d:.1f} mm deep (half of {hi[i] - lo[i]:.0f} mm), {hi[[j for j in range(3) if j != i][0]] - lo[[j for j in range(3) if j != i][0]]:.0f} x "
                        f"{hi[[j for j in range(3) if j != i][1]] - lo[[j for j in range(3) if j != i][1]]:.0f} mm crossing"])


# ---- mortise and tenon ------------------------------------------------------------------------------------------------------------
def mortise_tenon(rail, stile, axis, tenon_len=None, tenon_t=None, shoulder=0.0, clearance=0.1):
    """The end of `rail` enters `stile` along `axis`. Inside the stile the rail is reduced to a tenon (thickness tenon_t, default a
    third of the rail's thinner side; width = the wider side less a shoulder at each edge, centred) and the stile gets the mortise."""
    p = _axis(axis)
    lo, hi = _overlap(rail, stile)
    rl, rh = _bounds(rail)
    depth = hi[p] - lo[p]
    tip_low = abs(rl[p] - lo[p]) > TOL or False            # the rail comes in from the high side if it sticks out above the overlap
    if rh[p] > hi[p] + TOL and rl[p] >= lo[p] - TOL:
        tip_low = True                                       # sticks out above: its tip is the low end of the overlap
    elif rl[p] < lo[p] - TOL and rh[p] <= hi[p] + TOL:
        tip_low = False
    else:
        raise ValueError("the rail must enter the stile from one side only")
    tenon_len = depth if tenon_len is None else float(tenon_len)
    if tenon_len > depth + TOL:
        raise ValueError(f"the rail enters the stile only {depth:.1f} mm: a {tenon_len:.1f} mm tenon does not fit")
    cross = [i for i in range(3) if i != p]
    thin, wide = sorted(cross, key=lambda k: rh[k] - rl[k])
    t = (rh[thin] - rl[thin]) / 3 if tenon_t is None else float(tenon_t)
    w = (rh[wide] - rl[wide]) - 2 * shoulder
    if t <= 0 or w <= 0:
        raise ValueError("tenon thickness and width must be positive")
    tl, th = list(lo), list(hi)
    for k, size in ((thin, t), (wide, w)):
        c = (rl[k] + rh[k]) / 2
        tl[k], th[k] = c - size / 2, c + size / 2
    if tip_low:
        th[p] = lo[p] + tenon_len
    else:
        tl[p] = hi[p] - tenon_len
    new_rail = _cut(rail, lo, hi) + _box(tl, th) if depth > TOL else rail
    sl, sh = [x - clearance for x in tl], [x + clearance for x in th]
    return Joint("mortise_tenon", new_rail, _cut(stile, sl, sh), params=dict(tenon_t=t, tenon_w=w, tenon_len=tenon_len, shoulder=shoulder, clearance=clearance),
                 notes=[f"Mortise and tenon: tenon {t:.1f} x {w:.0f} x {tenon_len:.0f} mm (thickness x width x length), {shoulder:.0f} mm shoulders, {clearance:g} mm glue gap"])


# ---- dowel butt joint ------------------------------------------------------------------------------------------------------------
def _cylinder(axis, centre, r, z0, z1):
    """Cylinder of radius r along `axis` from coordinate z0 to z1; `centre` = the other two coordinates (in x, y, z order)."""
    c = Cylinder(r, z1 - z0)
    rot = {0: Rot(Y=90), 1: Rot(X=90), 2: Rot()}[axis]
    pos = [0.0, 0.0, 0.0]
    cross = [i for i in range(3) if i != axis]
    pos[cross[0]], pos[cross[1]], pos[axis] = centre[0], centre[1], (z0 + z1) / 2
    return Pos(*pos) * rot * c


def dowel_butt(a, b, dia=8.0, count=2, depth=15.0, edge=30.0, clearance=0.1, dowel_len=None):
    """Two boards face to face (touching, not overlapping), joined by dowels: each board gets `count` holes of `depth`; the dowels are
    loose parts. They are spread along the longer side of the contact area, `edge` from its ends, centred on the shorter one."""
    la, ha = _bounds(a)
    lb, hb = _bounds(b)
    contact = None
    for i in range(3):
        for first, second, f_hi, s_lo in ((a, b, ha[i], lb[i]), (b, a, hb[i], la[i])):
            if abs(f_hi - s_lo) < 1e-3:
                others = [j for j in range(3) if j != i]
                lo = [max(la[j], lb[j]) for j in others]
                hi = [min(ha[j], hb[j]) for j in others]
                if all(h - l > TOL for l, h in zip(lo, hi)):
                    contact = (i, f_hi, others, lo, hi)
    if contact is None:
        raise ValueError("the boards must touch face to face (no gap, no overlap) for a dowel joint")
    i, plane, others, lo, hi = contact
    long_k = 0 if hi[0] - lo[0] >= hi[1] - lo[1] else 1
    short_k = 1 - long_k
    mid_short = (lo[short_k] + hi[short_k]) / 2
    span0, span1 = lo[long_k] + edge, hi[long_k] - edge
    if span1 < span0:
        raise ValueError("the edge distance leaves no room for dowels on this joint")
    pos = [(span0 + span1) / 2] if count == 1 else [span0 + (span1 - span0) * n / (count - 1) for n in range(count)]
    dl = dowel_len if dowel_len is not None else 2 * depth - 2
    new_a, new_b, dowels = a, b, []
    for n, u in enumerate(pos):
        centre = [0.0, 0.0]
        centre[long_k], centre[short_k] = u, mid_short
        hole = _cylinder(i, centre, dia / 2 + clearance, plane - depth, plane + depth)
        new_a, new_b = new_a - hole, new_b - hole           # each board only contains its own half of the hole
        dowels.append((f"dowel_{n + 1}", _cylinder(i, centre, dia / 2, plane - dl / 2, plane + dl / 2)))
    return Joint("dowel_butt", new_a, new_b, hardware=dowels, params=dict(dia=dia, count=count, depth=depth, edge=edge, clearance=clearance, dowel_len=dl),
                 notes=[f"{count} dowels {dia:g} x {dl:g} mm, holes {depth:g} mm deep in each board, {edge:g} mm from the ends"])


CATALOG = [
    ("dowel_butt", "Dowel butt joint", "Two boards face to face joined by round dowels: frames, carcass corners, tabletops. Quick and strong with a jig."),
    ("dado", "Dado (housing)", "A groove across a board that takes the end of a shelf or divider: shelves, drawer runners. Stopped or through."),
    ("rabbet", "Rabbet", "A step along an edge that takes another board: back panels, drawer bottoms, box corners."),
    ("half_lap", "Half lap", "Two crossing boards each cut away by half the thickness so they interlock flush: frames, crossbars."),
    ("mortise_tenon", "Mortise and tenon", "A tongue on the rail end in a pocket of the leg: the classic frame joint for legs, rails and doors."),
]


def catalog(thickness=18.0):
    """The joints this module can cut with their usual proportions for boards of the given thickness (for menus and help)."""
    return [{"kind": k, "label": label, "description": text, "defaults": defaults(k, thickness)} for k, label, text in CATALOG]
