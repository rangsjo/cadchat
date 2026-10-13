"""Revolute-joint kinematics and collision checking for build123d parts (generic, no project specifics).

A Mechanism holds parts in a reference pose plus joints (origin/axis in that pose, degrees). `posed(values)` moves the
parts; `check(values)` reports overlapping pairs. Joint chains: leaf joint first, then each parent, i.e.
M = R_parent * ... * R_leaf (axes stay in the reference frame).
"""
import re
from itertools import combinations

from build123d import Axis, Vector


def mirrored_joint(j, suffix):
    """Mirror a joint across the YZ plane (x -> -x). Names/parents end in _<side>; axial vectors flip y and z."""
    base = lambda n: n.rsplit("_", 1)[0]
    o, a = j["origin"], j["axis"]
    return {**j,
            "name": f"{base(j['name'])}_{suffix}",
            "label": re.sub(r"\(\w+\)$", f"({suffix})", j["label"]),
            "parent": f"{base(j['parent'])}_{suffix}" if j.get("parent") else None,
            "origin": [-o[0], o[1], o[2]],
            "axis": [a[0], -a[1], -a[2]]}


class Mechanism:
    def __init__(self, parts, joints, presets, exempt=None):
        self.parts, self.joints = parts, joints
        self.jmap = {j["name"]: j for j in joints}
        self.presets = {k: {n: v.get(n, 0) for n in self.jmap} for k, v in presets.items()}
        self.exempt = exempt or (lambda a, b: False)        # pairs that legitimately touch/overlap (hardware, tenons)

    def posed(self, values):
        unknown = set(values) - set(self.jmap)
        if unknown:
            raise KeyError(f"unknown joint(s): {sorted(unknown)}")
        out = []
        for p in self.parts:
            shape, j = p["shape"], p.get("joint")
            while j:
                d = self.jmap[j]
                ang = float(values.get(j, 0))
                if ang:
                    shape = shape.rotate(Axis(Vector(*d["origin"]), Vector(*d["axis"])), ang)
                j = d["parent"]
            out.append((p["name"], shape))
        return out

    def check(self, values, min_volume=1.0):
        """[[partA, partB, overlap_mm3], ...] for pairs that overlap by more than min_volume."""
        pp = self.posed(values)
        bbs = [s.bounding_box() for _, s in pp]
        hits = []
        for i, j in combinations(range(len(pp)), 2):
            a, b = bbs[i], bbs[j]
            if (a.max.X < b.min.X or b.max.X < a.min.X or a.max.Y < b.min.Y or b.max.Y < a.min.Y
                    or a.max.Z < b.min.Z or b.max.Z < a.min.Z):
                continue
            if self.exempt(pp[i][0], pp[j][0]):
                continue
            v = pp[i][1].intersect(pp[j][1])
            vol = sum(s.volume for s in v) if v else 0
            if vol > min_volume:
                hits.append([pp[i][0], pp[j][0], round(vol)])
        return hits
