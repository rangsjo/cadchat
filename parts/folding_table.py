import sys
from pathlib import Path

from build123d import *

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import exchange
from cadview import load_params, params_out, publish_kinematic
from kinematics import Mechanism, mirrored_joint

# Folding drop-leaf table, built as a jointed mechanism. Reconstructed from photos and the dealer's sizes of a 1930s folding table
# (folded 23 cm, one leaf up 151 cm, fully open 280 cm, 90 cm deep, 73.5 cm high). What the photos show:
#   - two thick vertical PILLARS side by side, each topped by a wide CAP; the two caps are the narrow strips in the middle of the top,
#   - on each side a LEAF of two panels: the inner panel hangs from the cap, the outer one folds under it; folded, both hang under the
#     overhang of the cap, so the whole table closes to the 23 cm width of the two caps,
#   - ladder-shaped leg GATES (two uprights and two rails) hinged on vertical axes at the pillars; open they stand under the leaf,
#     folded they lie flat between the pillar and the hanging panels.
# The hinges and the rebate in the cap are my simplified reading of the photos, not measured from the original.

PARAMS = {  # name: (default, unit, group, description)
    "height": (735, "mm", "Overall", "Table height"),
    "depth": (900, "mm", "Overall", "Table depth"),
    "top_t": (30, "mm", "Top", "Thickness of the caps and the leaf panels"),
    "centre_w": (230, "mm", "Top", "Width of the two caps together (the folded width)"),
    "flap_w": (640, "mm", "Top", "Width of each leaf panel (two per side)"),
    "gap": (1, "mm", "Top", "Seam between top parts"),
    "pillar_t": (25, "mm", "Pillars", "Thickness of each centre pillar"),
    "skin": (12, "mm", "Hinge", "Depth of the hinge pin below the top surface (the lip of the cap above the hanging panels is about twice this)"),
    "frame_w": (26, "mm", "Gates", "Square section of the gate uprights"),
    "gate_len": (360, "mm", "Gates", "Length of a gate, from its hinge to its outer edge"),
    "gate_inset": (20, "mm", "Gates", "Distance of the gates from the long edges"),
    "rail_h": (40, "mm", "Gates", "Height of the gate rails"),
    "rail_t": (18, "mm", "Gates", "Thickness of the gate rails"),
    "low_z": (300, "mm", "Gates", "Centre height of the lower gate rail"),
    "hinge_r": (4, "mm", "Hinge", "Hinge barrel radius"),
}
V = load_params(__file__, PARAMS)

height, depth, top_t, centre_w, flap_w, gap = (V[k] for k in ("height", "depth", "top_t", "centre_w", "flap_w", "gap"))
pillar_t, skin, frame_w, gate_len, gate_inset = V["pillar_t"], V["skin"], V["frame_w"], V["gate_len"], V["gate_inset"]
rail_h, rail_t, low_z, hinge_r = V["rail_h"], V["rail_t"], V["low_z"], V["hinge_r"]
hinge_len = depth - 120
density = 700e-9                  # kg/mm^3, oak/birch

uz = height - top_t               # underside of the caps and the leaf panels
half_c = centre_w / 2             # outer edge of a cap
x1a, x1b = half_c + gap, half_c + gap + flap_w     # inner panel (open)
x2a, x2b = x1b + gap, x1b + gap + flap_w           # outer panel (open)
pin_x, pin_z = half_c - skin, height - skin        # pin of the inner hinge, in the cap's lip (the panel then hangs at x = half_c - top_t .. half_c)
seam_ab = x1b + gap / 2                            # underside hinge between the two panels

# rebate under the cap's outer part where the folded panels hang: two panel thicknesses plus the seam
pocket_x0 = half_c - 2 * top_t - gap
pocket_z1 = pin_z                                  # the lip of the cap above the pocket is `skin` thick
knuckle_r = gap + skin                             # radius of the rounded panel edge around the hinge pin (rule joint)

# gates: hinge corner on the pillar's outer face
pillar_x0, pillar_x1 = gap, gap + pillar_t         # right pillar x range; the left one is the mirror image
gate_x0 = pillar_x1 + 1
gate_y0 = depth / 2 - gate_inset - frame_w         # y of the upright's hinge-side edge, front gate (the back gate is its mirror image)


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def notch(shape, xa, za):
    """Hinge barrel recess in a panel corner at the axis (xa, za)."""
    return shape - Pos(xa, 0, za) * (Rot(X=90) * Cylinder(hinge_r + 1.5, hinge_len))


def cylinder_y(xa, za, r, length=None):
    return Pos(xa, 0, za) * (Rot(X=90) * Cylinder(r, length or depth + 2))


def barrel(xa, za):
    return Pos(xa, 0, za) * (Rot(X=90) * Cylinder(hinge_r, hinge_len))


def gate_parts():
    """Front gate in its open pose: a flat ladder in the XZ plane standing under the leaf, hinge corner at (gate_x0, gate_y0)."""
    y0, y1 = gate_y0, gate_y0 + frame_w
    ym = (y0 + y1) / 2
    xo = gate_x0 + gate_len
    return [
        ("post_in", box(gate_x0, gate_x0 + frame_w, y0, y1, 0, uz)),
        ("post_out", box(xo - frame_w, xo, y0, y1, 0, uz)),
        ("rail", box(gate_x0 + frame_w, xo - frame_w, ym - rail_t / 2, ym + rail_t / 2, uz - rail_h, uz)),
        ("stretcher", box(gate_x0 + frame_w, xo - frame_w, ym - rail_t / 2, ym + rail_t / 2, low_z - rail_h / 2, low_z + rail_h / 2)),
    ]


# ---------------------------------------------------------------- base (open) geometry, right side
J = {}      # joint base definitions (right side)
R = []      # (name, shape, joint) right side

J["flap_inner"] = dict(label="Inner panel hinge (top side)", group="Leaf", parent=None, origin=(pin_x, 0, pin_z), axis=(0, 1, 0), min=0, max=90)
J["flap_outer"] = dict(label="Outer panel hinge (underside)", group="Leaf", parent="flap_inner", origin=(seam_ab, 0, uz), axis=(0, 1, 0), min=0, max=180)
J["gate_front"] = dict(label="Front gate hinge", group="Gates", parent=None, origin=(gate_x0, gate_y0, 0), axis=(0, 0, -1), min=0, max=90)
J["gate_back"] = dict(label="Back gate hinge", group="Gates", parent=None, origin=(gate_x0, -gate_y0, 0), axis=(0, 0, 1), min=0, max=90)

# the cap has a rebate in its lower outer part: the folded panels hang in it, under a lip of the top
# rule joint at the inner hinge: the panel edge is rounded around the pin, the cap has the matching cove
cap = (box(gap / 2, half_c, -depth / 2, depth / 2, uz, height)
       - box(pocket_x0, half_c + gap, -depth / 2 - 1, depth / 2 + 1, uz - 1, pocket_z1)
       - cylinder_y(pin_x, pin_z, knuckle_r + 0.5))
knuckle = box(pin_x, x1a, -depth / 2, depth / 2, uz, height) & cylinder_y(pin_x, pin_z, knuckle_r)
inner_panel = box(x1a, x1b, -depth / 2, depth / 2, uz, height) + knuckle
R.append(("pillar", box(pillar_x0, pillar_x1, -depth / 2, depth / 2, 0, uz), None))
R.append(("cap", cap, None))
R.append(("flap_inner", inner_panel, "flap_inner"))
R.append(("flap_outer", notch(box(x2a, x2b, -depth / 2, depth / 2, uz, height), seam_ab, uz), "flap_outer"))
R.append(("hinge_inner_barrel", barrel(pin_x, pin_z), None))
R.append(("hinge_outer_barrel", barrel(seam_ab, uz), "flap_inner"))
for n, sh in gate_parts():
    R.append((f"gate_front_{n}", sh, "gate_front"))
    R.append((f"gate_back_{n}", mirror(sh, Plane.XZ), "gate_back"))
R[2] = ("flap_inner", notch(inner_panel, seam_ab, uz), "flap_inner")       # the seam barrel also needs its recess in this panel


def meta_of(name):
    if name.startswith("hinge_"):
        return dict(role="hardware", material="brass")
    if name.startswith(("flap_", "cap")):
        return dict(role="top", material="oak")
    if name.startswith("pillar"):
        return dict(role="pillar", material="birch")
    return dict(role="gate", material="birch")


parts = []
for sfx, sx in (("R", 1), ("L", -1)):
    for n, sh, jt in R:
        parts.append(dict(name=f"{n}_{sfx}", shape=sh if sx == 1 else mirror(sh, Plane.YZ),
                          joint=f"{jt}_{sfx}" if jt else None, **meta_of(n)))
right_joints = [dict(name=f"{n}_R", label=f"{d['label']} (R)", group=d["group"],
                     parent=f"{d['parent']}_R" if d["parent"] else None,
                     origin=list(d["origin"]), axis=list(d["axis"]), min=d["min"], max=d["max"]) for n, d in J.items()]
joints = right_joints + [mirrored_joint(j, "L") for j in right_joints]

CLOSED_SIDE = {"flap_inner": 90, "flap_outer": 180, "gate_front": 90, "gate_back": 90}
presets = {
    "open": {},
    "one_leaf": {f"{k}_L": v for k, v in CLOSED_SIDE.items()},                    # left leaf folded, right leaf up
    "closed": {f"{k}_{s}": v for s in "RL" for k, v in CLOSED_SIDE.items()},
}

# ---------------------------------------------------------------- constraints (how things are connected)
fmt = lambda v: f"{v:g}"
constraints = []
for sfx in "RL":
    n = lambda base: f"{base}_{sfx}"
    gate_names = lambda g: [n(f"gate_{g}_{p}") for p in ("post_in", "post_out", "rail", "stretcher")]
    constraints += [
        dict(id=n("hinge_inner"), kind="revolute", label=f"Cap hinge ({sfx}): cap ↔ inner panel (pin in the top skin)",
             a=n("cap"), b=n("flap_inner"), joint=n("flap_inner"), parts=[n("cap"), n("flap_inner"), n("hinge_inner_barrel")],
             params=["centre_w", "skin", "top_t"],
             expr=f"pin at x = centre_w/2 - skin = {fmt(pin_x)}, z = height - skin = {fmt(pin_z)}: the panel swings down and hangs under the cap at x = {fmt(half_c - top_t)}..{fmt(half_c)}"),
        dict(id=n("hinge_outer"), kind="revolute", label=f"Underside hinge ({sfx}): inner ↔ outer panel",
             a=n("flap_inner"), b=n("flap_outer"), joint=n("flap_outer"), parts=[n("flap_inner"), n("flap_outer"), n("hinge_outer_barrel")],
             params=["flap_w", "gap", "hinge_r"],
             expr=f"axis x = {fmt(seam_ab)} on the underside: the outer panel folds under the inner one (the other way than the cap hinge)"),
        dict(id=n("pillar_cap"), kind="fixed", label=f"Pillar carries the cap ({sfx})", a=n("pillar"), b=n("cap"),
             parts=[n("pillar"), n("cap")], params=["pillar_t", "top_t"], expr=f"pillar {fmt(pillar_t)} mm thick under a cap {fmt(half_c)} mm wide"),
        dict(id=n("rebate"), kind="dimension", label=f"Rebate under the cap for the hanging panels ({sfx})", a=None, b=None,
             parts=[n("cap"), n("flap_inner"), n("flap_outer")], params=["top_t", "skin", "gap", "centre_w"],
             expr=f"rebate from x = {fmt(pocket_x0)} to the cap edge, up to z = {fmt(pocket_z1)}: leaves a lip of {fmt(height - pocket_z1)} mm"),
        dict(id=n("hw_inner_barrel"), kind="fixed", label=f"Hinge barrel pinned in the cap lip ({sfx})", a=n("hinge_inner_barrel"), b=n("cap"),
             parts=[n("hinge_inner_barrel"), n("cap")], params=["hinge_r", "skin"], expr="brass barrel along the depth less 120 mm"),
        dict(id=n("hw_outer_barrel"), kind="fixed", label=f"Hinge barrel on the inner panel ({sfx})", a=n("hinge_outer_barrel"), b=n("flap_inner"),
             parts=[n("hinge_outer_barrel"), n("flap_inner")], params=["hinge_r"], expr="notch radius = hinge_r + 1.5"),
    ]
    for g in ("front", "back"):
        constraints += [
            dict(id=n(f"gate_{g}"), kind="revolute", label=f"{g.capitalize()} gate hinge ({sfx}): vertical axis at the pillar",
                 a=n("pillar"), b=n(f"gate_{g}_post_in"), joint=n(f"gate_{g}"), parts=[n("pillar")] + gate_names(g),
                 params=["frame_w", "gate_len", "gate_inset", "pillar_t"],
                 expr=f"hinge corner at x = {fmt(gate_x0)}, y = {fmt((1 if g == 'front' else -1) * gate_y0)}; the {fmt(gate_len)} mm ladder swings 90 deg to lie flat"),
            dict(id=n(f"gate_{g}_frame"), kind="fixed", label=f"{g.capitalize()} gate: rails fixed between the uprights ({sfx})",
                 a=n(f"gate_{g}_rail"), b=n(f"gate_{g}_post_out"), parts=gate_names(g), params=["rail_h", "rail_t", "low_z"],
                 expr=f"upper rail under the leaf (z {fmt(uz - rail_h)}..{fmt(uz)}), lower rail centred at z = {fmt(low_z)}"),
        ]
total_open = 2 * (half_c + gap + 2 * flap_w + gap)
constraints += [
    dict(id="dim_open", kind="dimension", label="Open length", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("cap", "flap_"))], params=["centre_w", "flap_w", "gap"],
         expr=f"length = centre_w + 4*flap_w + 5*gap = {fmt(total_open)} mm (dealer: 2800)"),
    dict(id="dim_folded", kind="dimension", label="Folded width = the two caps", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("cap", "pillar"))], params=["centre_w"],
         expr=f"width = centre_w = {fmt(centre_w)} mm (dealer: 230)"),
    dict(id="dim_leg_height", kind="dimension", label="Gate and pillar height under the top", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("gate_", "pillar"))], params=["height", "top_t"],
         expr=f"height - top_t = {fmt(height)} - {fmt(top_t)} = {fmt(uz)} mm"),
]
params_json = params_out(PARAMS, V)


def _exempt(a, b):
    return a.startswith("hinge_") or b.startswith("hinge_")        # brass hardware is not modelled to the last detail


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
        print(f"{name:9s} size {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm | wood {wood:.0f} L "
              f"~{wood * 1e6 * density:.0f} kg | collisions: {hits if hits else 'none'}")
        exchange.export_step_assembly(pp, f"exports/folding_table_{name}.step", name=f"folding_table_{name}")
        export_stl(comp, f"exports/folding_table_{name}.stl")
    publish_kinematic(parts, joints, presets, "parts/folding_table.py", params_json, constraints)
