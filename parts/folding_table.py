import math
import sys
from pathlib import Path

from build123d import *

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import exchange
from cadview import load_params, params_out, publish_kinematic
from kinematics import Mechanism, mirrored_joint

# Folding drop-leaf table, built as a jointed mechanism. Reconstructed from photos and the dealer's sizes of a 1930s folding table
# (folded 23 cm, one leaf up 151 cm, fully open 280 cm, 90 cm deep, 73.5 cm high). Chain of six sheets, left to right:
#   A outer sheet - B base top - C centre sheet - D centre sheet - E base top - F outer sheet
# hinged A-B under, B-C under, C-D over, D-E under, E-F under (all 90 deg at most). B and E sit on a pillar with two fixed legs and
# two fold-out legs (45 deg hinge) that lie flat inside the thickness of the pillar block when folded: 8 legs. Folding: the outer
# sheets hang down, then C and D fold down into a V (their top faces meet at the C-D hinge, which ends at the bottom of the V) while
# the bases slide together; the slide is coupled to the fold angle. A loose filler sheet then fills the gap between the base tops.
# Joint "side" R is the right half (D, E, F); L is its mirror image (C, B, A).
# The hinge details and the sheet and leg sizes are my simplified reading of the photos, not measured from the original.

PARAMS = {  # name: (default, unit, group, description)
    "height": (735, "mm", "Overall", "Table height"),
    "depth": (900, "mm", "Overall", "Table depth"),
    "top_t": (22, "mm", "Top", "Sheet thickness"),
    "centre_w": (230, "mm", "Top", "Folded width of the table"),
    "sheet_w": (664, "mm", "Top", "Width of a centre sheet (C, D), pivot to the C-D hinge"),
    "outer_w": (664, "mm", "Top", "Width of an outer sheet (A, F)"),
    "gap": (1, "mm", "Top", "Seam between top parts"),
    "post": (52, "mm", "Base", "Square section of the fixed legs = thickness of the pillar block (panel and two folded legs side by side)"),
    "panel_t": (16, "mm", "Base", "Thickness of the pillar panel between the fixed legs"),
    "leg": (16, "mm", "Legs", "Square section of the fold-out legs"),
    "gate_len": (700, "mm", "Legs", "Length of a fold-out leg frame, hinge to the foot (almost the whole pillar block)"),
    "gate_inset": (20, "mm", "Legs", "Distance of the fixed legs from the long edges"),
    "stretcher_h": (40, "mm", "Legs", "Height of the stretcher"),
    "stretcher_t": (12, "mm", "Legs", "Thickness of the stretcher"),
    "low_z": (250, "mm", "Legs", "Centre height of the stretcher"),
    "hinge_r": (4, "mm", "Hinge", "Hinge barrel radius"),
}
V = load_params(__file__, PARAMS)

height, depth, top_t, centre_w, sheet_w, outer_w, gap = (V[k] for k in ("height", "depth", "top_t", "centre_w", "sheet_w", "outer_w", "gap"))
post, panel_t, leg, gate_len, gate_inset = V["post"], V["panel_t"], V["leg"], V["gate_len"], V["gate_inset"]
stretcher_h, stretcher_t, low_z, hinge_r = V["stretcher_h"], V["stretcher_t"], V["low_z"], V["hinge_r"]
hinge_len = depth - 120
density = 700e-9                  # kg/mm^3, oak/birch

uz = height - top_t               # underside of the sheets
half_c = centre_w / 2             # folded: outer face of the hanging outer sheets
t, g = top_t, gap

# folded (closed) layout, right half: V of the centre sheets, base top, outer sheet hanging on the outside
x_ef = half_c - t                 # E-F pivot (underside); the outer sheet hangs at x_ef .. half_c
x_de = g / 2 + t                  # D-E pivot (underside); the centre sheet hangs at g/2 .. g/2 + t
slide_max = sheet_w - t           # the base slides this far from fully open to folded
X = slide_max                     # open x = closed x + X for everything that rides on the base
bx0 = x_de + g + 2                # pillar block (fixed legs, panel, folded fold-out legs) under the base top
bx1 = bx0 + post
y_h = depth / 2 - gate_inset - post          # hinge corner of the fold-out legs = inner face of the fixed leg
pin_z = height                    # the C-D hinge pin sits on the top surface
filler_w = 2 * x_de - g           # fills the gap between the folded base tops


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def barrel(xa, za):
    return Pos(xa, 0, za) * (Rot(X=90) * Cylinder(hinge_r, hinge_len))


def frame_parts():
    """Both fold-out legs lying flat in the pillar block (folded), turned 45 deg out into the open pose. The outer leg lies on the outer side
    of the panel, hinged at the front fixed leg, and swings out towards the outer sheet; the inner leg lies on the inner side, hinged at the
    back fixed leg, and swings towards the centre. Each is a full-height leg at the far end plus a stretcher back to the hinge."""
    out = []
    # outer leg: hinge corner (bx1, +y_h), flat along -y
    ya = y_h - gate_len
    xs = bx1 - leg + (leg - stretcher_t) / 2
    turn = Axis((bx1, y_h, 0), (0, 0, 1))
    out += [("gate_out_leg", box(bx1 - leg, bx1, ya, ya + leg, 0, uz).rotate(turn, 45)),
            ("gate_out_stretcher", box(xs, xs + stretcher_t, ya + leg, y_h, low_z - stretcher_h / 2, low_z + stretcher_h / 2).rotate(turn, 45))]
    # inner leg: hinge corner (bx0, -y_h), flat along +y
    yb = -y_h + gate_len
    xs = bx0 + (leg - stretcher_t) / 2
    turn = Axis((bx0, -y_h, 0), (0, 0, 1))
    out += [("gate_in_leg", box(bx0, bx0 + leg, yb - leg, yb, 0, uz).rotate(turn, 45)),
            ("gate_in_stretcher", box(xs, xs + stretcher_t, -y_h, yb - leg, low_z - stretcher_h / 2, low_z + stretcher_h / 2).rotate(turn, 45))]
    return out


def shift(shape):
    return Pos(X, 0, 0) * shape


# ---------------------------------------------------------------- right half in the open pose (D, E, F)
x_de_o, x_ef_o = x_de + X, x_ef + X
J, R = {}, []
J["fold"] = dict(label="Centre sheet fold (top hinge 90°)", group="Sheets", parent="slide", origin=(x_de_o, 0, uz), axis=(0, -1, 0), min=0, max=90)
J["outer"] = dict(label="Outer sheet fold (underside hinge)", group="Sheets", parent="slide", origin=(x_ef_o, 0, uz), axis=(0, 1, 0), min=0, max=90)
J["gate_out"] = dict(label="Outer fold-out leg hinge (towards the outer sheet)", group="Legs", parent="slide", origin=(bx1 + X, y_h, 0), axis=(0, 0, -1), min=0, max=45)
J["gate_in"] = dict(label="Inner fold-out leg hinge (towards the centre)", group="Legs", parent="slide", origin=(bx0 + X, -y_h, 0), axis=(0, 0, -1), min=0, max=45)
# the slide is coupled to the fold angle: the pins of the two centre sheets must stay together at x = +-gap/2 (four-bar closure)
_table = [[a, round(sheet_w * (1 - math.cos(math.radians(a))) - t * math.sin(math.radians(a)), 4)] for a in [i * 2.5 for i in range(37)]]
J["slide"] = dict(label="Base slide (coupled to the fold)", group="Sheets", type="prismatic", parent=None, origin=(0, 0, 0), axis=(-1, 0, 0),
                  min=-1, max=slide_max, mimic=dict(of="fold", table=_table))

R.append(("top", shift(box(x_de + g, x_ef - g, -depth / 2, depth / 2, uz, height)), "slide"))
R.append(("centre", box(g / 2, x_de_o - g, -depth / 2, depth / 2, uz, height), "fold"))
R.append(("outer", box(x_ef_o + g, x_ef_o + outer_w, -depth / 2, depth / 2, uz, height), "outer"))
R.append(("pillar", shift(box(bx0 + leg + 1, bx0 + leg + 1 + panel_t, -y_h, y_h, 0, uz)), "slide"))
R.append(("hinge_pin_barrel", barrel(g / 2, pin_z), "fold"))
R.append(("hinge_de_barrel", barrel(x_de_o, uz), "slide"))
R.append(("hinge_ef_barrel", barrel(x_ef_o, uz), "slide"))
for sgn, name in ((1, "front"), (-1, "back")):
    R.append((f"post_{name}", shift(box(bx0, bx1, *sorted((sgn * y_h, sgn * (y_h + post))), 0, uz)), "slide"))
for n, sh in frame_parts():
    R.append((n, shift(sh), n.rsplit("_", 1)[0]))


def meta_of(name):
    if name.startswith("hinge_"):
        return dict(role="hardware", material="brass")
    if name.startswith(("top", "centre", "outer", "filler")):
        return dict(role="top", material="oak")
    if name.startswith("pillar"):
        return dict(role="pillar", material="birch")
    return dict(role="leg", material="birch")


parts = []
for sfx, sx in (("R", 1), ("L", -1)):
    for n, sh, jt in R:
        parts.append(dict(name=f"{n}_{sfx}", shape=sh if sx == 1 else mirror(sh, Plane.YZ), joint=f"{jt}_{sfx}" if jt else None, **meta_of(n)))
# loose filler: stored low between the bases in the open pose, lifted into the gap between the base tops when folded
parts.append(dict(name="filler", shape=box(-filler_w / 2, filler_w / 2, -depth / 2, depth / 2, 0, t), joint="filler", **meta_of("filler")))
right_joints = [dict(name=f"{n}_R", label=f"{d['label']} (R)", group=d["group"], type=d.get("type", "revolute"),
                     parent=f"{d['parent']}_R" if d["parent"] else None, origin=list(d["origin"]), axis=list(d["axis"]), min=d["min"], max=d["max"],
                     **({"mimic": {"of": f"{d['mimic']['of']}_R", "table": d["mimic"]["table"]}} if d.get("mimic") else {}))
                for n, d in J.items()]
joints = right_joints + [mirrored_joint(j, "L") for j in right_joints]
joints.append(dict(name="filler", label="Filler sheet (lift into the gap)", group="Sheets", type="prismatic", parent=None, origin=[0, 0, 0],
                   axis=[0, 0, 1], min=0, max=uz))

FOLDED = {"fold": 90, "outer": 90, "gate_out": 45, "gate_in": 45}
presets = {
    "open": {},
    "one_leaf": {**{f"fold_{s}": 90 for s in "RL"}, **{f"gate_in_{s}": 45 for s in "RL"}, "filler": uz},   # centre folded, outer sheets and outer legs still out: 151 cm
    "closed": {**{f"{k}_{s}": v for s in "RL" for k, v in FOLDED.items()}, "filler": uz},
}

# ---------------------------------------------------------------- constraints (how things are connected)
fmt = lambda v: f"{v:g}"
constraints = []
for sfx in "RL":
    n = lambda base: f"{base}_{sfx}"
    side = "D-E / E-F" if sfx == "R" else "C-B / B-A"
    constraints += [
        dict(id=n("fold"), kind="revolute", label=f"Centre sheet hinge ({sfx}): pivot under the base top, other end pinned to its twin on top",
             a=n("top"), b=n("centre"), joint=n("fold"), parts=[n("top"), n("centre"), n("hinge_de_barrel"), n("hinge_pin_barrel")],
             params=["sheet_w", "top_t", "gap"],
             expr=f"underside pivot at x = {fmt(x_de_o)} (open); the sheet hangs at x = {fmt(g / 2)}..{fmt(g / 2 + t)} when folded; 0-90 deg"),
        dict(id=n("slide"), kind="prismatic", label=f"Base slide ({sfx}): coupled to the centre sheet fold", a=None, b=n("top"), joint=n("slide"),
             parts=[n("top"), n("pillar")], params=["sheet_w", "top_t"],
             expr=f"slide = sheet_w*(1 - cos a) - top_t*sin a, 0 to {fmt(slide_max)} mm: keeps the C-D hinge pin at the centre line"),
        dict(id=n("outer"), kind="revolute", label=f"Outer sheet hinge ({sfx}): underside hinge at the outer edge of the base top",
             a=n("top"), b=n("outer"), joint=n("outer"), parts=[n("top"), n("outer"), n("hinge_ef_barrel")], params=["outer_w", "top_t", "gap"],
             expr=f"pivot at x = {fmt(x_ef_o)} on the underside; hangs at x = {fmt(x_ef)}..{fmt(half_c)} when folded; 0-90 deg"),
        dict(id=n("pillar_top"), kind="fixed", label=f"Pillar block carries the base top ({sfx})", a=n("pillar"), b=n("top"),
             parts=[n("pillar"), n("post_front"), n("post_back"), n("top")], params=["post", "panel_t"],
             expr=f"panel {fmt(panel_t)} mm and two fixed legs {fmt(post)} x {fmt(post)} mm under the base top"),
    ]
    for g_, what in (("out", "towards the outer sheet, hinged at the front fixed leg"), ("in", "towards the centre, hinged at the back fixed leg")):
        constraints += [
            dict(id=n(f"gate_{g_}"), kind="revolute", label=f"{g_.capitalize()}er fold-out leg hinge ({sfx}): vertical axis at a fixed leg",
                 a=n("post_front" if g_ == "out" else "post_back"), b=n(f"gate_{g_}_leg"), joint=n(f"gate_{g_}"),
                 parts=[n("post_front" if g_ == "out" else "post_back"), n(f"gate_{g_}_leg"), n(f"gate_{g_}_stretcher")], params=["leg", "gate_len", "post"],
                 expr=f"swings {what}; open it stands {fmt(gate_len * 0.707)} mm out at 45 deg and carries the sheet, folded it lies flat beside the panel"),
        ]
total_open = 2 * (x_ef_o + outer_w)
constraints += [
    dict(id="dim_open", kind="dimension", label="Open length", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("top", "centre", "outer"))], params=["centre_w", "sheet_w", "outer_w", "top_t"],
         expr=f"length = 2*(centre_w/2 - top_t + sheet_w - top_t + outer_w) = {fmt(total_open)} mm (dealer: 2800)"),
    dict(id="dim_folded", kind="dimension", label="Folded width", a=None, b=None, parts=[p["name"] for p in parts if p["name"].startswith("outer")],
         params=["centre_w"], expr=f"width = centre_w = {fmt(centre_w)} mm (dealer: 230)"),
    dict(id="dim_filler", kind="dimension", label="Filler sheet", a=None, b=None, parts=["filler"], params=["top_t", "centre_w"],
         expr=f"{fmt(filler_w)} mm wide: fills the gap between the folded base tops"),
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
