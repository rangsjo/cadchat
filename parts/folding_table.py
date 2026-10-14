import math
import re
import sys
from pathlib import Path

from build123d import *

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import exchange
import linkage
from cadview import load_params, params_out, publish_kinematic
from kinematics import Mechanism, mirrored_joint

# Folding drop-leaf table built as a jointed mechanism. A narrow fixed centre top carries two flaps on each side:
#   - the inner flap is hinged on the underside and folds DOWN (it hangs beside the centre),
#   - the outer flap is hinged on the TOP side and folds OVER, onto the outside of the hanging inner flap (opposite sense).
# The legs under each side form a "W" seen from above: a zigzag of four links joined by vertical hinges, with a leg at
# every vertex. The last leg stands under the outermost table top. Folded, the links lie side by side like a concertina:
# each link is a little longer than the previous one so the legs stagger, and the rails sit at different heights and on
# alternating sides of the leg line, so everything interleaves into one compact bundle under the centre top.
# Example model for cadchat; the mechanics are a simplified design, not a reference to any real product.

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
    "leg_amp": (150, "mm", "W frame", "Legs stand this far to either side of the centre line (half amplitude of the W)"),
    "leg_x_outer": (1330, "mm", "W frame", "x of the outermost leg, under the last table top"),
    "post_x": (62, "mm", "W frame", "x of the fixed post under the centre top"),
    "link_step": (70, "mm", "W frame", "Each link is this much longer than the one before (legs stagger when folded)"),
    "rail_h": (50, "mm", "Rails", "Upper rail height"),
    "rail_t": (22, "mm", "Rails", "Upper rail thickness"),
    "rail_clear": (3, "mm", "Rails", "Gap between a rail and the legs it passes when folded"),
    "rail_pitch": (56, "mm", "Rails", "Height difference between the upper rails of neighbouring links"),
    "low_h": (40, "mm", "Rails", "Low stretcher height"),
    "low_t": (20, "mm", "Rails", "Low stretcher thickness"),
    "low_z": (300, "mm", "Rails", "Centre height of the first low stretcher"),
    "low_pitch": (50, "mm", "Rails", "Height difference between the low stretchers of neighbouring links"),
    "hinge_r": (4, "mm", "Hinges", "Hinge barrel radius"),
    "hinge_leaf_w": (35, "mm", "Hinges", "Hinge leaf width"),
}
V = load_params(__file__, PARAMS)

height, depth, top_t, centre_w, flap_w, gap = (V[k] for k in ("height", "depth", "top_t", "centre_w", "flap_w", "gap"))
leg_w, leg_d = V["leg_w"], V["leg_d"]
leg_fillet = min(5, leg_w / 4)
rail_h, rail_t, rail_pitch, rail_clear, low_h, low_t, low_z, low_pitch = (V[k] for k in ("rail_h", "rail_t", "rail_pitch", "rail_clear", "low_h", "low_t", "low_z", "low_pitch"))
hinge_r, hinge_leaf_t, hinge_leaf_w, hinge_len = V["hinge_r"], 2, V["hinge_leaf_w"], depth - 120
density = 700e-9                  # kg/mm^3, beech
N_LINKS = 4
RAIL_SIDES = (1, -1, 1, -1)       # which side of its link each rail sits on (+1 left of the travel direction)

uz = height - top_t               # underside of the top
half_c = centre_w / 2
x1a, x1b = half_c + gap, half_c + gap + flap_w   # inner flap span (open)
x2a, x2b = x1b + gap, x1b + gap + flap_w         # outer flap span (open)
seam_in, seam_out = half_c + gap / 2, x1b + gap / 2   # hinge axes: inner on the underside, outer on the top side

# W frame in plan view (right side; the left side is its mirror image)
dxs = linkage.solve_zigzag(V["leg_x_outer"] - V["post_x"], V["leg_amp"], V["link_step"], N_LINKS)
verts = linkage.zigzag_vertices(V["post_x"], V["leg_amp"], dxs)          # V0 = fixed post, V1..V4 = legs
dirs = linkage.link_angles(verts)
fold = linkage.fold_angles(verts)                                         # hinge angles that stack all links along y
link_len = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(verts, verts[1:])]


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def rect_leg(x, y, rot=0):
    """Leg (short side leg_w, long side leg_d), long side along X at rot=0, turned by rot degrees about Z."""
    with BuildPart() as p:
        Box(leg_d, leg_w, uz, align=(Align.CENTER, Align.CENTER, Align.MIN))
        fillet(p.edges().filter_by(Axis.Z), radius=leg_fillet)
    return Pos(x, y, 0) * Rot(Z=rot) * p.part


def link_rail(k, z_mid, h, t):
    """Rail of link k (1-based) beside the legs, offset to one side of the link (RAIL_SIDES) so folded links pass the legs."""
    (x0, y0), (x1, y1) = verts[k - 1], verts[k]
    th = math.radians(dirs[k - 1])
    off = RAIL_SIDES[k - 1] * (leg_w / 2 + t / 2 + rail_clear)
    nx, ny = -math.sin(th), math.cos(th)
    mx, my = (x0 + x1) / 2 + nx * off, (y0 + y1) / 2 + ny * off
    return Pos(mx, my, z_mid) * Rot(Z=dirs[k - 1]) * Box(link_len[k - 1], t, h)


def notch(shape, xa, za):
    """Hinge barrel recess in a panel corner at the axis (xa, za)."""
    return shape - Pos(xa, 0, za) * (Rot(X=90) * Cylinder(hinge_r + 1.5, hinge_len))


def hinge_parts(xa, za, leaf_dir, parent_joint, child_joint, tag):
    """Barrel on the axis and two leaves, below (leaf_dir -1) or above (+1) the axis height."""
    z0, z1 = (za - hinge_leaf_t, za) if leaf_dir < 0 else (za, za + hinge_leaf_t)
    barrel = Pos(xa, 0, za) * (Rot(X=90) * Cylinder(hinge_r, hinge_len))
    leaf_p = box(xa - hinge_leaf_w, xa, -hinge_len / 2, hinge_len / 2, z0, z1)
    leaf_c = box(xa, xa + hinge_leaf_w, -hinge_len / 2, hinge_len / 2, z0, z1)
    return [(f"hinge_{tag}_barrel", barrel, parent_joint),
            (f"hinge_{tag}_leaf_a", leaf_p, parent_joint),
            (f"hinge_{tag}_leaf_b", leaf_c, child_joint)]


# ---------------------------------------------------------------- base (open) geometry, right side
J = {}      # joint base definitions (right side)
R = []      # (name, shape, joint) right side

J["flap_inner"] = dict(label="Inner flap hinge", group="Flaps", parent=None, origin=(seam_in, 0, uz), axis=(0, 1, 0), min=0, max=90)
J["flap_outer"] = dict(label="Outer flap hinge (top side)", group="Flaps", parent="flap_inner", origin=(seam_out, 0, height), axis=(0, -1, 0), min=0, max=180)
R.append(("flap_inner", notch(notch(box(x1a, x1b, -depth / 2, depth / 2, uz, height), seam_in, uz), seam_out, height), "flap_inner"))
R.append(("flap_outer", notch(box(x2a, x2b, -depth / 2, depth / 2, uz, height), seam_out, height), "flap_outer"))
R += hinge_parts(seam_in, uz, -1, None, "flap_inner", "inner")
R += hinge_parts(seam_out, height, +1, "flap_inner", "flap_outer", "outer")

R.append(("post", rect_leg(*verts[0], rot=90), None))          # fixed, long side along y like the folded stack
for k in range(1, N_LINKS + 1):
    jn = f"arm_{k}"
    J[jn] = dict(label=f"W hinge {k}", group="Legs (W frame)", parent=f"arm_{k - 1}" if k > 1 else None,
                 origin=(verts[k - 1][0], verts[k - 1][1], 0), axis=(0, 0, 1), min=-180, max=180)
    R.append((f"leg_{k}", rect_leg(*verts[k], rot=dirs[k - 1]), jn))
    R.append((f"arm_rail_{k}", link_rail(k, uz - rail_h / 2 - (k - 1) * rail_pitch, rail_h, rail_t), jn))
    R.append((f"stretcher_{k}", link_rail(k, low_z - (k - 1) * low_pitch, low_h, low_t), jn))

centre = box(-half_c, half_c, -depth / 2, depth / 2, uz, height)
centre = notch(notch(centre, seam_in, uz), -seam_in, uz)


def meta_of(name):
    if name.startswith("hinge_"):
        return dict(role="hardware", material="brass")
    role = "top" if name.startswith(("flap_", "centre_")) else "leg" if name.startswith(("post", "leg_")) else "rail"
    return dict(role=role, material="beech")


parts = [dict(name="centre_top", shape=centre, joint=None, **meta_of("centre_top"))]
for sfx, sx in (("R", 1), ("L", -1)):
    for n, sh, jt in R:
        parts.append(dict(name=f"{n}_{sfx}", shape=sh if sx == 1 else mirror(sh, Plane.YZ),
                          joint=f"{jt}_{sfx}" if jt else None, **meta_of(n)))
right_joints = [dict(name=f"{n}_R", label=f"{d['label']} (R)", group=d["group"],
                     parent=f"{d['parent']}_R" if d["parent"] else None,
                     origin=list(d["origin"]), axis=list(d["axis"]), min=d["min"], max=d["max"]) for n, d in J.items()]
joints = right_joints + [mirrored_joint(j, "L") for j in right_joints]

fold_pose = {f"arm_{k + 1}_{s}": round(a, 6) for k, a in enumerate(fold) for s in "RL"}
presets = {
    "open": {},
    "half": {f"flap_outer_{s}": 180 for s in "RL"},                       # outer flaps stacked on the inner ones
    "closed": {**fold_pose, **{f"flap_inner_{s}": 90 for s in "RL"}, **{f"flap_outer_{s}": 180 for s in "RL"}},
}


# ---------------------------------------------------------------- constraints (how things are connected)
fmt = lambda v: f"{v:g}"
constraints = []
for sfx in "RL":
    n = lambda base: f"{base}_{sfx}"
    constraints += [
        dict(id=n("hinge_inner"), kind="revolute", label=f"Underside hinge ({sfx}): centre top ↔ inner flap",
             a="centre_top", b=n("flap_inner"), joint=n("flap_inner"),
             parts=["centre_top", n("flap_inner"), n("hinge_inner_barrel")], params=["centre_w", "gap", "hinge_r"],
             expr=f"axis x = centre_w/2 + gap/2 = {fmt(seam_in)}, at the underside: the inner flap folds down"),
        dict(id=n("hinge_outer"), kind="revolute", label=f"Top hinge ({sfx}): inner ↔ outer flap",
             a=n("flap_inner"), b=n("flap_outer"), joint=n("flap_outer"),
             parts=[n("flap_inner"), n("flap_outer"), n("hinge_outer_barrel")], params=["flap_w", "gap", "hinge_r"],
             expr=f"axis x = centre_w/2 + flap_w + 1.5*gap = {fmt(seam_out)}, on the top: the outer flap folds over (opposite sense)"),
    ]
    for tag, pa, pc in (("inner", "centre_top", n("flap_inner")), ("outer", n("flap_inner"), n("flap_outer"))):
        constraints += [
            dict(id=n(f"hw_{tag}_barrel"), kind="fixed", label=f"Hinge barrel pinned to {pa}", a=n(f"hinge_{tag}_barrel"), b=pa,
                 parts=[n(f"hinge_{tag}_barrel"), pa], params=["hinge_r"], expr="notch radius = hinge_r + 1.5"),
            dict(id=n(f"hw_{tag}_leaf_a"), kind="fixed", label=f"Hinge leaf screwed to {pa}", a=n(f"hinge_{tag}_leaf_a"), b=pa,
                 parts=[n(f"hinge_{tag}_leaf_a"), pa], params=["hinge_leaf_w"], expr="leaf on the parent panel"),
            dict(id=n(f"hw_{tag}_leaf_b"), kind="fixed", label=f"Hinge leaf screwed to {pc}", a=n(f"hinge_{tag}_leaf_b"), b=pc,
                 parts=[n(f"hinge_{tag}_leaf_b"), pc], params=["hinge_leaf_w"], expr="leaf on the child panel"),
        ]
    constraints.append(dict(id=n("post_mount"), kind="fixed", label=f"Post fixed under the centre top ({sfx})", a=n("post"), b="centre_top",
                            parts=[n("post"), "centre_top"], params=["post_x", "leg_amp"],
                            expr=f"post at (x, y) = ({fmt(verts[0][0])}, {fmt(verts[0][1])}), first vertex of the W"))
    for k in range(1, N_LINKS + 1):
        prev = n("post") if k == 1 else n(f"leg_{k - 1}")
        constraints += [
            dict(id=n(f"knee_{k}"), kind="revolute", label=f"W hinge {k} ({sfx}): vertical axis through {'the post' if k == 1 else f'leg {k - 1}'}",
                 a=prev, b=n(f"leg_{k}"), joint=n(f"arm_{k}"),
                 parts=[prev, n(f"leg_{k}"), n(f"arm_rail_{k}"), n(f"stretcher_{k}")],
                 params=["leg_amp", "leg_x_outer", "post_x", "link_step"],
                 expr=f"link {k} is {fmt(round(link_len[k - 1], 1))} mm long (link_step = {fmt(V['link_step'])} longer each); closed hinge angle {fmt(round(fold[k - 1], 1))} deg"),
            dict(id=n(f"tenon_rail_{k}"), kind="fixed", label=f"Upper rail {k} fixed to leg {k} ({sfx})",
                 a=n(f"arm_rail_{k}"), b=n(f"leg_{k}"), parts=[n(f"arm_rail_{k}"), n(f"leg_{k}")],
                 params=["rail_h", "rail_t", "rail_pitch"], expr=f"rail centre z = {fmt(uz - rail_h / 2 - (k - 1) * rail_pitch)}; its own height band lets the links interleave"),
            dict(id=n(f"tenon_low_{k}"), kind="fixed", label=f"Low stretcher {k} fixed to leg {k} ({sfx})",
                 a=n(f"stretcher_{k}"), b=n(f"leg_{k}"), parts=[n(f"stretcher_{k}"), n(f"leg_{k}")],
                 params=["low_h", "low_t", "low_z", "low_pitch"], expr=f"stretcher centre z = {fmt(low_z - (k - 1) * low_pitch)}"),
        ]
total_open = centre_w + 4 * flap_w + 4 * gap
constraints += [
    dict(id="dim_length", kind="dimension", label="Open length from centre and flaps", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("centre_top", "flap_"))],
         params=["centre_w", "flap_w", "gap"], expr=f"length = centre_w + 4*flap_w + 4*gap = {fmt(total_open)} mm"),
    dict(id="dim_leg_height", kind="dimension", label="Leg height from underside of the top", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("post_", "leg_"))],
         params=["height", "top_t"], expr=f"leg height = height - top_t = {fmt(height)} - {fmt(top_t)} = {fmt(height - top_t)} mm"),
    dict(id="dim_w_frame", kind="dimension", label="W frame: legs reach the last table top", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("post_", "leg_", "arm_rail_", "stretcher_"))],
         params=["leg_amp", "leg_x_outer", "post_x", "link_step"],
         expr=f"vertices x = {', '.join(fmt(round(v[0])) for v in verts)}; y alternates +/-{fmt(V['leg_amp'])}; outermost leg under the last top (x up to {fmt(x2b)})"),
]
params_json = params_out(PARAMS, V)


# ---------------------------------------------------------------- posing and checks
_RAIL = re.compile(r"^(arm_rail|stretcher)_(\d)_([RL])$")


def _exempt(a, b):
    if a.startswith("hinge_") or b.startswith("hinge_"):
        return True
    for x, y in ((a, b), (b, a)):               # a rail is fixed to the two legs it connects (the pivot ends turn about them)
        m = _RAIL.match(x)
        if m:
            k, side = int(m.group(2)), m.group(3)
            if y in (f"leg_{k}_{side}", f"post_{side}" if k == 1 else f"leg_{k - 1}_{side}"):
                return True
    return False


mech = Mechanism(parts, joints, presets, exempt=_exempt)
presets = mech.presets
posed, check_pose = mech.posed, mech.check


if __name__ == "__main__":
    Path("exports").mkdir(exist_ok=True)
    for name, vals in presets.items():
        pp = posed(vals)
        comp = Compound([s for _, s in pp], label=f"folding_table_{name}")
        bb = comp.bounding_box()
        wood = sum(s.volume for n, s in pp if not n.startswith("hinge_")) / 1e6
        hits = check_pose(vals)
        print(f"{name:6s} size {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm | wood {wood:.0f} L "
              f"~{wood * 1e6 * density:.0f} kg | collisions: {hits if hits else 'none'}")
        exchange.export_step_assembly(pp, f"exports/folding_table_{name}.step", name=f"folding_table_{name}")
        export_stl(comp, f"exports/folding_table_{name}.stl")
    publish_kinematic(parts, joints, presets, "parts/folding_table.py", params_json, constraints)
