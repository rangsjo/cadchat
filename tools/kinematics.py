"""Revolute and prismatic joint kinematics and collision checking for build123d parts (generic, no project specifics).

A Mechanism holds parts in a reference pose plus joints (origin/axis in that pose; a joint with "mimic": {"of", "table": [[driver, value], ...]} is driven by another joint; degrees, or mm for a joint with "type": "prismatic"). `posed(values)` moves the
parts; `check(values)` reports overlapping pairs. Joint chains: leaf joint first, then each parent, i.e.
M = R_parent * ... * R_leaf (axes stay in the reference frame).
"""
import re
from itertools import combinations

from build123d import Axis, Location, Vector


def mirrored_joint(j, suffix):
    """Mirror a joint across the YZ plane (x -> -x). Names/parents end in _<side>; axial vectors flip y and z."""
    base = lambda n: n.rsplit("_", 1)[0]
    o, a = j["origin"], j["axis"]
    axis = [-a[0], a[1], a[2]] if j.get("type") == "prismatic" else [a[0], -a[1], -a[2]]      # a slide is a polar vector, a hinge an axial one
    return {**j,
            "name": f"{base(j['name'])}_{suffix}",
            "label": re.sub(r"\(\w+\)$", f"({suffix})", j["label"]),
            "parent": f"{base(j['parent'])}_{suffix}" if j.get("parent") else None,
            "origin": [-o[0], o[1], o[2]],
            "axis": axis,
            **({"mimic": {**j["mimic"], "of": f"{base(j['mimic']['of'])}_{suffix}"}} if j.get("mimic") else {})}


def _interp(table, x):
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


class Mechanism:
    def __init__(self, parts, joints, presets, exempt=None, cache=True):
        self.parts, self.joints = parts, joints
        self.jmap = {j["name"]: j for j in joints}
        self.presets = {k: {n: v.get(n, 0) for n in self.jmap} for k, v in presets.items()}
        self.exempt = exempt or (lambda a, b: False)        # pairs that legitimately touch/overlap (hardware, tenons)
        self.cache, self.stats, self._rigid = cache, {"boolean_calls": 0}, {}

    def resolve(self, values):
        """Joint values with the coupled (mimic) joints filled in from their drivers by piecewise-linear table lookup."""
        unknown = set(values) - set(self.jmap)
        if unknown:
            raise KeyError(f"unknown joint(s): {sorted(unknown)}")
        out = dict(values)
        for n, j in self.jmap.items():
            m = j.get("mimic")
            if m:
                out[n] = _interp(m["table"], float(values.get(m["of"], 0)))
        return out

    def posed(self, values):
        values = self.resolve(values)
        out = []
        for p in self.parts:
            shape, j = p["shape"], p.get("joint")
            while j:
                d = self.jmap[j]
                ang = float(values.get(j, 0))
                if ang and d.get("type") == "prismatic":
                    shape = shape.moved(Location(Vector(*d["axis"]).normalized() * ang))
                elif ang:
                    shape = shape.rotate(Axis(Vector(*d["origin"]), Vector(*d["axis"])), ang)
                j = d["parent"]
            out.append((p["name"], shape))
        return out

    def _chain(self, part, values):
        """Joints (with their angles) that actually move this part; parts with equal chains move as one rigid body."""
        chain, j = [], part.get("joint")
        while j:
            a = float(values.get(j, 0))
            if a:
                chain.append((j, a))
            j = self.jmap[j]["parent"]
        return tuple(chain)

    def check(self, values, min_volume=1.0):
        """[[partA, partB, overlap_mm3], ...] for pairs that overlap by more than min_volume.
        Pairs that do not move relative to each other are computed once and reused in every pose."""
        values = self.resolve(values)
        pp = self.posed(values)
        chains = [self._chain(p, values) for p in self.parts]
        bbs = [s.bounding_box() for _, s in pp]
        hits = []
        for i, j in combinations(range(len(pp)), 2):
            a, b = bbs[i], bbs[j]
            if (a.max.X < b.min.X or b.max.X < a.min.X or a.max.Y < b.min.Y or b.max.Y < a.min.Y
                    or a.max.Z < b.min.Z or b.max.Z < a.min.Z):
                continue
            if self.exempt(pp[i][0], pp[j][0]):
                continue
            rigid = self.cache and chains[i] == chains[j]
            if rigid and (i, j) in self._rigid:
                vol = self._rigid[(i, j)]
            else:
                v = pp[i][1].intersect(pp[j][1])
                self.stats["boolean_calls"] += 1
                vol = sum(s.volume for s in v) if v else 0
                if rigid:
                    self._rigid[(i, j)] = vol
            if vol > min_volume:
                hits.append([pp[i][0], pp[j][0], round(vol)])
        return hits
