import math
from itertools import combinations
from pathlib import Path
import sys

from build123d import *

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from cadview import load_params, params_out, publish_kinematic
from kinematics import Mechanism, mirrored_joint

# Folding drop-leaf table built as a jointed mechanism: a narrow fixed centre top with two hinged flaps per side
# (they hang when folded) and swing-out gate legs. Example model for cadchat; the hinge types, joint limits and
# leg mechanics are a simplified design, not a reference to any real product.

# Parameters (mm). Defaults here; the viewer's Parameters panel overrides them through .cad/params.json.
PARAMS = {  # name: (default, unit, group, description)
    "height": (720, "mm", "Overall", "Table height"),
    "depth": (900, "mm", "Overall", "Table depth"),
    "top_t": (25, "mm", "Top", "Top and flap thickness"),
    "centre_w": (230, "mm", "Top", "Fixed centre top width"),
    "flap_w": (650, "mm", "Top", "Width of each flap"),
    "gap": (1, "mm", "Top", "Seam between top parts"),
    "leg_w": (40, "mm", "Legs", "Leg section, short side"),
    "leg_d": (60, "mm", "Legs", "Leg section, long side"),
    "leg_inset": (55, "mm", "Legs", "Leg centre inset from the top's edge"),
    "leg_x_open": (722, "mm", "Legs", "Swing-leg x position when open"),
    "post_x_front": (22, "mm", "Legs", "Front pivot post x"),
    "post_x_back": (66, "mm", "Legs", "Back pivot post x"),
    "rail_h": (50, "mm", "Rails", "Upper arm rail height"),
    "rail_t": (22, "mm", "Rails", "Upper arm rail thickness"),
    "low_h": (40, "mm", "Rails", "Low stretcher height"),
    "low_t": (20, "mm", "Rails", "Low stretcher thickness"),
    "low_z": (300, "mm", "Rails", "Low stretcher centre height"),
    "hinge_r": (4, "mm", "Hinges", "Hinge barrel radius"),
    "hinge_leaf_w": (35, "mm", "Hinges", "Hinge leaf width"),
}
V = load_params(__file__, PARAMS)

height, depth, top_t, centre_w, flap_w, gap = (V[k] for k in ("height", "depth", "top_t", "centre_w", "flap_w", "gap"))
leg_w, leg_d, leg_inset, leg_x_open = V["leg_w"], V["leg_d"], V["leg_inset"], V["leg_x_open"]
leg_fillet = min(5, leg_w / 4)
rail_h, rail_t, low_h, low_t, low_z = (V[k] for k in ("rail_h", "rail_t", "low_h", "low_t", "low_z"))
post_x = {1: V["post_x_front"], -1: V["post_x_back"]}   # offset so folded arms pass each other
leg_y = depth / 2 - leg_inset
hinge_r, hinge_leaf_t, hinge_leaf_w, hinge_len = V["hinge_r"], 2, V["hinge_leaf_w"], depth - 120
density = 700e-9                  # kg/mm^3, beech

uz = height - top_t               # underside of the top
half_c = centre_w / 2
x1a, x1b = half_c + gap, half_c + gap + flap_w   # inner flap span (open)
x2a, x2b = x1b + gap, x1b + gap + flap_w         # outer flap span (open)
seam_in, seam_out = half_c + gap / 2, x1b + gap / 2   # hinge axes (at the underside, in the seam)


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def rect_leg(x, y, rot=0):
    """40x60 leg; long side along X at rot=0, turned by rot degrees about Z."""
    with BuildPart() as p:
        Box(leg_d, leg_w, uz, align=(Align.CENTER, Align.CENTER, Align.MIN))
        fillet(p.edges().filter_by(Axis.Z), radius=leg_fillet)
    return Pos(x, y, 0) * Rot(Z=rot) * p.part


def rail(p0, p1, z_mid, h, t, h_start, h_end):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    dist = math.hypot(dx, dy)
    ux, uy = dx / dist, dy / dist
    length = dist - h_start - h_end
    mid = (p0[0] + ux * (h_start + length / 2), p0[1] + uy * (h_start + length / 2), z_mid)
    return Pos(*mid) * Rot(Z=math.degrees(math.atan2(dy, dx))) * Box(length, t, h)


def notch(shape, xa):
    """Hinge barrel recess in a panel corner."""
    cut = Pos(xa, 0, uz) * (Rot(X=90) * Cylinder(hinge_r + 1.5, hinge_len))
    return shape - cut


def hinge_parts(xa, parent_joint, child_joint, tag):
    barrel = Pos(xa, 0, uz) * (Rot(X=90) * Cylinder(hinge_r, hinge_len))
    leaf_p = box(xa - hinge_leaf_w, xa, -hinge_len / 2, hinge_len / 2, uz - hinge_leaf_t, uz)
    leaf_c = box(xa, xa + hinge_leaf_w, -hinge_len / 2, hinge_len / 2, uz - hinge_leaf_t, uz)
    return [(f"hinge_{tag}_barrel", barrel, parent_joint),
            (f"hinge_{tag}_leaf_a", leaf_p, parent_joint),
            (f"hinge_{tag}_leaf_b", leaf_c, child_joint)]


# ---------------------------------------------------------------- base (open) geometry, right side
J = {}      # joint base definitions (right side)
R = []      # (name, shape, joint) right side

J["flap_inner"] = dict(label="Inner flap hinge", group="Flaps", parent=None, origin=(seam_in, 0, uz), axis=(0, 1, 0), min=0, max=90)
J["flap_outer"] = dict(label="Outer flap hinge", group="Flaps", parent="flap_inner", origin=(seam_out, 0, uz), axis=(0, 1, 0), min=0, max=180)
R.append(("flap_inner", notch(notch(box(x1a, x1b, -depth / 2, depth / 2, uz, height), seam_in), seam_out), "flap_inner"))
R.append(("flap_outer", notch(box(x2a, x2b, -depth / 2, depth / 2, uz, height), seam_out), "flap_outer"))
R += hinge_parts(seam_in, None, "flap_inner", "inner")
R += hinge_parts(seam_out, "flap_inner", "flap_outer", "outer")

for t in (1, -1):
    side = "front" if t == 1 else "back"
    px = post_x[t]
    post, end = (px, t * leg_y), (leg_x_open, t * leg_y)
    jn = f"arm_{side}"
    J[jn] = dict(label=f"{side.capitalize()} swing arm", group="Legs", parent=None,
                 origin=(px, t * leg_y, 0), axis=(0, 0, -t), min=0, max=90)
    R.append((f"post_{side}", rect_leg(*post, rot=90), None))
    R.append((f"swing_leg_{side}", rect_leg(*end), jn))
    R.append((f"arm_rail_{side}", rail(post, end, uz - rail_h / 2, rail_h, rail_t, leg_w / 2, leg_d / 2), jn))
    R.append((f"stretcher_{side}", rail(post, end, low_z, low_h, low_t, leg_w / 2, leg_d / 2), jn))

centre = box(-half_c, half_c, -depth / 2, depth / 2, uz, height)
centre = notch(notch(centre, seam_in), -seam_in)
def meta_of(name):
    if name.startswith("hinge_"):
        return dict(role="hardware", material="brass")
    role = "top" if name.startswith("flap_") else "leg" if name.startswith(("post_", "swing_leg_")) else "rail"
    return dict(role=role, material="beech")


parts = [dict(name="centre_top", shape=centre, joint=None, **meta_of("flap_"))]
for sfx, sx in (("R", 1), ("L", -1)):
    for n, sh, jt in R:
        parts.append(dict(name=f"{n}_{sfx}", shape=sh if sx == 1 else mirror(sh, Plane.YZ),
                          joint=f"{jt}_{sfx}" if jt else None, **meta_of(n)))
right_joints = [dict(name=f"{n}_R", label=f"{d['label']} (R)", group=d["group"],
                     parent=f"{d['parent']}_R" if d["parent"] else None,
                     origin=list(d["origin"]), axis=list(d["axis"]), min=d["min"], max=d["max"]) for n, d in J.items()]
joints = right_joints + [mirrored_joint(j, "L") for j in right_joints]

presets = {
    "open": {},
    "half": {f"flap_outer_{s}": 90 for s in "RL"},
    "closed": {**{f"flap_inner_{s}": 90 for s in "RL"}, **{f"flap_outer_{s}": 180 for s in "RL"},
               **{f"arm_{a}_{s}": 90 for a in ("front", "back") for s in "RL"}},
}


# ---------------------------------------------------------------- constraints (how things are connected)
fmt = lambda v: f"{v:g}"
constraints = []
for sfx in "RL":
    n = lambda base: f"{base}_{sfx}"
    constraints += [
        dict(id=n("hinge_inner"), kind="revolute", label=f"Hinge ({sfx}): centre top \u2194 inner flap",
             a="centre_top", b=n("flap_inner"), joint=n("flap_inner"),
             parts=["centre_top", n("flap_inner"), n("hinge_inner_barrel")], params=["centre_w", "gap", "hinge_r"],
             expr=f"axis x = centre_w/2 + gap/2 = {fmt(seam_in)}, z = underside"),
        dict(id=n("hinge_outer"), kind="revolute", label=f"Hinge ({sfx}): inner \u2194 outer flap",
             a=n("flap_inner"), b=n("flap_outer"), joint=n("flap_outer"),
             parts=[n("flap_inner"), n("flap_outer"), n("hinge_outer_barrel")], params=["flap_w", "gap", "hinge_r"],
             expr=f"axis x = centre_w/2 + flap_w + 1.5*gap = {fmt(seam_out)}"),
    ]
    for tag, jn in (("inner", n("flap_inner")), ("outer", n("flap_outer"))):
        pa = "centre_top" if tag == "inner" else n("flap_inner")
        pc = n("flap_inner") if tag == "inner" else n("flap_outer")
        constraints += [
            dict(id=n(f"hw_{tag}_barrel"), kind="fixed", label=f"Hinge barrel pinned to {pa}", a=n(f"hinge_{tag}_barrel"), b=pa,
                 parts=[n(f"hinge_{tag}_barrel"), pa], params=["hinge_r"], expr="notch radius = hinge_r + 1.5"),
            dict(id=n(f"hw_{tag}_leaf_a"), kind="fixed", label=f"Hinge leaf screwed to {pa}", a=n(f"hinge_{tag}_leaf_a"), b=pa,
                 parts=[n(f"hinge_{tag}_leaf_a"), pa], params=["hinge_leaf_w"], expr="leaf under the parent panel"),
            dict(id=n(f"hw_{tag}_leaf_b"), kind="fixed", label=f"Hinge leaf screwed to {pc}", a=n(f"hinge_{tag}_leaf_b"), b=pc,
                 parts=[n(f"hinge_{tag}_leaf_b"), pc], params=["hinge_leaf_w"], expr="leaf under the child panel"),
        ]
    for side, t in (("front", 1), ("back", -1)):
        arm_len = leg_x_open - post_x[t]
        constraints += [
            dict(id=n(f"pivot_{side}"), kind="revolute", label=f"Pivot ({sfx}): {side} post \u2192 swing arm",
                 a=n(f"post_{side}"), b=n(f"swing_leg_{side}"), joint=n(f"arm_{side}"),
                 parts=[n(f"post_{side}"), n(f"swing_leg_{side}"), n(f"arm_rail_{side}"), n(f"stretcher_{side}")],
                 params=[f"post_x_{side}", "leg_x_open", "leg_inset"],
                 expr=f"arm length = leg_x_open - post_x_{side} = {fmt(leg_x_open)} - {fmt(post_x[t])} = {fmt(arm_len)}"),
            dict(id=n(f"tenon_rail_{side}"), kind="fixed", label=f"Arm rail tenoned into {side} swing leg",
                 a=n(f"arm_rail_{side}"), b=n(f"swing_leg_{side}"), parts=[n(f"arm_rail_{side}"), n(f"swing_leg_{side}")],
                 params=["rail_h", "rail_t"], expr="rail ends at the leg face"),
            dict(id=n(f"tenon_low_{side}"), kind="fixed", label=f"Low stretcher tenoned into {side} swing leg",
                 a=n(f"stretcher_{side}"), b=n(f"swing_leg_{side}"), parts=[n(f"stretcher_{side}"), n(f"swing_leg_{side}")],
                 params=["low_h", "low_t", "low_z"], expr=f"stretcher centre z = low_z = {fmt(low_z)}"),
            dict(id=n(f"post_mount_{side}"), kind="fixed", label=f"{side.capitalize()} post fixed under the centre top",
                 a=n(f"post_{side}"), b="centre_top", parts=[n(f"post_{side}"), "centre_top"],
                 params=[f"post_x_{side}", "leg_inset"], expr=f"post at (x, y) = ({fmt(post_x[t])}, {fmt(t * leg_y)})"),
        ]
total_open = centre_w + 4 * flap_w + 4 * gap
constraints += [
    dict(id="dim_length", kind="dimension", label="Open length from centre and flaps", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("centre_top", "flap_"))],
         params=["centre_w", "flap_w", "gap"], expr=f"length = centre_w + 4*flap_w + 4*gap = {fmt(total_open)} mm"),
    dict(id="dim_leg_height", kind="dimension", label="Leg height from underside of the top", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("post_", "swing_leg_"))],
         params=["height", "top_t"], expr=f"leg height = height - top_t = {fmt(height)} - {fmt(top_t)} = {fmt(height - top_t)} mm"),
    dict(id="dim_leg_y", kind="dimension", label="Leg position from the long edges", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("post_", "swing_leg_"))],
         params=["depth", "leg_inset"], expr=f"leg y = +/-(depth/2 - leg_inset) = +/-{fmt(leg_y)} mm"),
]
params_json = params_out(PARAMS, V)


# ---------------------------------------------------------------- posing and checks
def _exempt(a, b):
    if a.startswith("hinge_") or b.startswith("hinge_"):
        return True
    for x, y in ((a, b), (b, a)):               # rail/stretcher is tenoned into its own post
        if x.startswith("post_"):
            for pre in ("arm_rail_", "stretcher_"):
                if y.startswith(pre) and y[len(pre):] == x[len("post_"):]:
                    return True
    return False


mech = Mechanism(parts, joints, presets, exempt=_exempt)
presets = mech.presets
posed, check_pose = mech.posed, mech.check


if __name__ == "__main__":
    for name, vals in presets.items():
        pp = posed(vals)
        comp = Compound([s for _, s in pp], label=f"folding_table_{name}")
        bb = comp.bounding_box()
        wood = sum(s.volume for n, s in pp if not n.startswith("hinge_")) / 1e6
        hits = check_pose(vals)
        print(f"{name:6s} size {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm | wood {wood:.0f} L "
              f"~{wood * 1e6 * density:.0f} kg | collisions: {hits if hits else 'none'}")
        export_step(comp, f"exports/folding_table_{name}.step")
        export_stl(comp, f"exports/folding_table_{name}.stl")
    publish_kinematic(parts, joints, presets, "parts/folding_table.py", params_json, constraints)
