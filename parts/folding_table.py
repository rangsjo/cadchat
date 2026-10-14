import sys
from pathlib import Path

from build123d import *

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import exchange
from cadview import load_params, params_out, publish_kinematic
from kinematics import Mechanism, mirrored_joint

# Folding drop-leaf table, built as a jointed mechanism. Reconstructed from photos and the dealer's sizes of a 1930s folding table
# (folded 23 cm, one leaf up 151 cm, fully open 280 cm, 90 cm deep, 73.5 cm high). The reading of the photos:
#   - two BASES, each a pillar under a cap; the two bases slide together to the 23 cm folded width,
#   - per side three sheets: a CENTRE sheet hinged on the inner edge of the cap, a MIDDLE sheet hinged on the outer edge and an OUTER
#     sheet that folds under the middle one; plus one small FILLER sheet in the centre that closes the gap between the two centre
#     sheets when they hang down (6 sheets + 1),
#   - on each side of each base an N-shaped leg frame (two legs and a diagonal brace): 4 frames, 8 legs. Open it stands at 45 deg
#     under the middle sheet, folded (45 deg hinge) it lies flat between the pillar and the hanging sheets.
# The hinges and the rebates in the cap are my simplified reading of the photos, not measured from the original.

PARAMS = {  # name: (default, unit, group, description)
    "height": (735, "mm", "Overall", "Table height"),
    "depth": (900, "mm", "Overall", "Table depth"),
    "top_t": (22, "mm", "Top", "Sheet thickness"),
    "centre_w": (230, "mm", "Top", "Folded width of the table"),
    "sheet_w": (427, "mm", "Top", "Width of each of the six sheets (centre, middle, outer, per side)"),
    "gap": (1, "mm", "Top", "Seam between top parts"),
    "pillar_t": (18, "mm", "Bases", "Thickness of each pillar"),
    "skin": (12, "mm", "Hinge", "Depth of the hinge pin below the top surface (the lip of the cap above the hanging sheets is about twice this)"),
    "leg": (18, "mm", "Legs", "Square section of the legs"),
    "gate_len": (300, "mm", "Legs", "Distance between the two legs of an N frame"),
    "gate_inset": (20, "mm", "Legs", "Distance of the frames from the long edges"),
    "brace_w": (60, "mm", "Legs", "Width of the diagonal brace"),
    "brace_t": (12, "mm", "Legs", "Thickness of the diagonal brace"),
    "hinge_r": (4, "mm", "Hinge", "Hinge barrel radius"),
}
V = load_params(__file__, PARAMS)

height, depth, top_t, centre_w, sheet_w, gap = (V[k] for k in ("height", "depth", "top_t", "centre_w", "sheet_w", "gap"))
pillar_t, skin, leg, gate_len, gate_inset = V["pillar_t"], V["skin"], V["leg"], V["gate_len"], V["gate_inset"]
brace_w, brace_t, hinge_r = V["brace_w"], V["brace_t"], V["hinge_r"]
hinge_len = depth - 120
density = 700e-9                  # kg/mm^3, oak/birch

uz = height - top_t               # underside of the sheets
half_c = centre_w / 2             # folded: outer face of the hanging outer sheets
pin_z = height - skin
knuckle_r = gap + skin            # radius of the rounded sheet edge around a hinge pin (rule joint)

# folded layout of one half from the centre outwards: hanging centre sheet, pillar, leg frame, two hanging sheets
stack = top_t + gap + pillar_t + gap + leg + gap + 2 * top_t + gap
ih0 = half_c - stack              # folded: inner edge of the cap
f_half = ih0 - gap                # half width of the filler sheet
slide_max = sheet_w + gap         # how far each base slides out: the centre sheet then fills the gap up to the filler
ie = ih0 + slide_max              # open: inner edge of the cap ...
eo = half_c + slide_max           # ... and outer edge
pin_c = ie + skin                 # pin of the centre sheet (the sheet hangs at x = ie .. ie + top_t)
pin_m = eo - skin                 # pin of the middle sheet (hangs at x = eo - top_t .. eo)
x1a, x1b = eo + gap, eo + gap + sheet_w            # middle sheet
x2a, x2b = x1b + gap, x1b + gap + sheet_w          # outer sheet
seam = x1b + gap / 2                               # underside hinge between middle and outer sheet
pillar_x0 = ie + top_t + gap
pillar_x1 = pillar_x0 + pillar_t
gate_x0 = pillar_x1 + gap                          # the flat frame lies in gate_x0 .. gate_x0 + leg
gate_y0 = depth / 2 - gate_inset                   # hinge corner (front frame; the back frame is its mirror image)
pocket_x0 = eo - 2 * top_t - gap


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def cylinder_y(xa, za, r, length=None):
    return Pos(xa, 0, za) * (Rot(X=90) * Cylinder(r, length or depth + 2))


def barrel(xa, za):
    return cylinder_y(xa, za, hinge_r, hinge_len)


def notch(shape, xa, za):
    return shape - cylinder_y(xa, za, hinge_r + 1.5, hinge_len)


def frame_parts():
    """Front N frame lying flat (folded), then turned 45 deg out into its open pose: two legs and a diagonal brace."""
    y_in, y_out = gate_y0 - leg, gate_y0 - gate_len                           # lower y edge of the hinge leg / far leg's far edge
    legs = [("leg_in", box(gate_x0, gate_x0 + leg, y_in, gate_y0, 0, uz)),
            ("leg_out", box(gate_x0, gate_x0 + leg, y_out, y_out + leg, 0, uz))]
    ya, yb = y_in, y_out + leg                                               # inner faces of the two legs
    xb = gate_x0 + (leg - brace_t) / 2
    pts = [Vector(xb, ya, uz), Vector(xb, ya, uz - brace_w), Vector(xb, yb, 0), Vector(xb, yb, brace_w)]
    band = extrude(Face(Wire.make_polygon(pts, close=True)), amount=brace_t, dir=(1, 0, 0))
    brace = band & box(xb - 1, xb + brace_t + 1, yb, ya, 0, uz)
    turn = Axis((gate_x0, gate_y0, 0), (0, 0, 1))
    return [(n, s.rotate(turn, 45)) for n, s in legs + [("brace", brace)]]


# ---------------------------------------------------------------- right side in the open pose
J = {}      # joint base definitions (right side)
R = []      # (name, shape, joint) right side

J["slide"] = dict(label="Base slide", group="Bases", type="prismatic", parent=None, origin=(0, 0, 0), axis=(-1, 0, 0), min=0, max=slide_max)
J["centre"] = dict(label="Centre sheet hinge (top side)", group="Sheets", parent="slide", origin=(pin_c, 0, pin_z), axis=(0, -1, 0), min=0, max=90)
J["middle"] = dict(label="Middle sheet hinge (top side)", group="Sheets", parent="slide", origin=(pin_m, 0, pin_z), axis=(0, 1, 0), min=0, max=90)
J["outer"] = dict(label="Outer sheet hinge (underside)", group="Sheets", parent="middle", origin=(seam, 0, uz), axis=(0, 1, 0), min=0, max=180)
J["gate_front"] = dict(label="Front leg frame hinge", group="Legs", parent="slide", origin=(gate_x0, gate_y0, 0), axis=(0, 0, -1), min=0, max=45)
J["gate_back"] = dict(label="Back leg frame hinge", group="Legs", parent="slide", origin=(gate_x0, -gate_y0, 0), axis=(0, 0, 1), min=0, max=45)

# the cap has a rebate under each edge where a sheet hangs, below a lip of the top; rule joint at the pins:
# the sheet edge is rounded around the pin, the cap has the matching cove
cap = (box(ie, eo, -depth / 2, depth / 2, uz, height)
       - box(ie - gap, ie + top_t + gap, -depth / 2 - 1, depth / 2 + 1, uz - 1, pin_z)
       - box(pocket_x0, eo + gap, -depth / 2 - 1, depth / 2 + 1, uz - 1, pin_z)
       - cylinder_y(pin_c, pin_z, knuckle_r + 0.5) - cylinder_y(pin_m, pin_z, knuckle_r + 0.5))
centre = box(ih0, ie - gap, -depth / 2, depth / 2, uz, height) + (box(ie - gap, pin_c, -depth / 2, depth / 2, uz, height) & cylinder_y(pin_c, pin_z, knuckle_r))
middle = box(x1a, x1b, -depth / 2, depth / 2, uz, height) + (box(pin_m, x1a, -depth / 2, depth / 2, uz, height) & cylinder_y(pin_m, pin_z, knuckle_r))
R.append(("pillar", box(pillar_x0, pillar_x1, -depth / 2, depth / 2, 0, uz), "slide"))
R.append(("cap", cap, "slide"))
R.append(("centre", centre, "centre"))
R.append(("middle", notch(middle, seam, uz), "middle"))
R.append(("outer", notch(box(x2a, x2b, -depth / 2, depth / 2, uz, height), seam, uz), "outer"))
R.append(("hinge_centre_barrel", barrel(pin_c, pin_z), "slide"))
R.append(("hinge_middle_barrel", barrel(pin_m, pin_z), "slide"))
R.append(("hinge_outer_barrel", barrel(seam, uz), "middle"))
for n, sh in frame_parts():
    R.append((f"gate_front_{n}", sh, "gate_front"))
    R.append((f"gate_back_{n}", mirror(sh, Plane.XZ), "gate_back"))


def meta_of(name):
    if name.startswith("hinge_"):
        return dict(role="hardware", material="brass")
    if name.startswith(("centre", "middle", "outer", "cap", "filler")):
        return dict(role="top", material="oak")
    if name.startswith("pillar"):
        return dict(role="pillar", material="birch")
    return dict(role="leg", material="birch")


parts = [dict(name="filler", shape=box(-f_half, f_half, -depth / 2, depth / 2, uz, height), joint=None, **meta_of("filler"))]
for sfx, sx in (("R", 1), ("L", -1)):
    for n, sh, jt in R:
        parts.append(dict(name=f"{n}_{sfx}", shape=sh if sx == 1 else mirror(sh, Plane.YZ),
                          joint=f"{jt}_{sfx}" if jt else None, **meta_of(n)))
right_joints = [dict(name=f"{n}_R", label=f"{d['label']} (R)", group=d["group"], type=d.get("type", "revolute"),
                     parent=f"{d['parent']}_R" if d["parent"] else None,
                     origin=list(d["origin"]), axis=list(d["axis"]), min=d["min"], max=d["max"]) for n, d in J.items()]
joints = right_joints + [mirrored_joint(j, "L") for j in right_joints]

CLOSED_SIDE = {"slide": slide_max, "centre": 90, "middle": 90, "outer": 180, "gate_front": 45, "gate_back": 45}
presets = {
    "open": {},
    "one_leaf": {f"{k}_L": v for k, v in CLOSED_SIDE.items()},                    # left half folded and slid in, right half open
    "closed": {f"{k}_{s}": v for s in "RL" for k, v in CLOSED_SIDE.items()},
}

# ---------------------------------------------------------------- constraints (how things are connected)
fmt = lambda v: f"{v:g}"
constraints = []
for sfx in "RL":
    n = lambda base: f"{base}_{sfx}"
    frame = lambda g: [n(f"gate_{g}_{p}") for p in ("leg_in", "leg_out", "brace")]
    constraints += [
        dict(id=n("slide"), kind="prismatic", label=f"Base slide ({sfx}): pillar, cap and everything on them", a=None, b=n("pillar"), joint=n("slide"),
             parts=[n("pillar"), n("cap")], params=["centre_w", "sheet_w", "gap"],
             expr=f"slides {fmt(slide_max)} mm = sheet_w + gap, so the open centre sheet exactly fills the space up to the filler"),
        dict(id=n("hinge_centre"), kind="revolute", label=f"Centre sheet hinge ({sfx}): pin in the top skin at the inner edge of the cap",
             a=n("cap"), b=n("centre"), joint=n("centre"), parts=[n("cap"), n("centre"), n("hinge_centre_barrel")],
             params=["skin", "top_t", "sheet_w"], expr=f"pin at x = {fmt(pin_c)}, z = height - skin = {fmt(pin_z)}; the sheet swings down and hangs under the cap lip"),
        dict(id=n("hinge_middle"), kind="revolute", label=f"Middle sheet hinge ({sfx}): pin in the top skin at the outer edge of the cap",
             a=n("cap"), b=n("middle"), joint=n("middle"), parts=[n("cap"), n("middle"), n("hinge_middle_barrel")],
             params=["skin", "top_t", "sheet_w"], expr=f"pin at x = {fmt(pin_m)}, z = {fmt(pin_z)}; the sheet hangs at x = {fmt(eo - top_t)}..{fmt(eo)}"),
        dict(id=n("hinge_outer"), kind="revolute", label=f"Underside hinge ({sfx}): middle ↔ outer sheet",
             a=n("middle"), b=n("outer"), joint=n("outer"), parts=[n("middle"), n("outer"), n("hinge_outer_barrel")],
             params=["sheet_w", "gap", "hinge_r"], expr=f"axis x = {fmt(seam)} on the underside: the outer sheet folds under the middle one (the other way than the top hinges)"),
        dict(id=n("pillar_cap"), kind="fixed", label=f"Pillar carries the cap ({sfx})", a=n("pillar"), b=n("cap"),
             parts=[n("pillar"), n("cap")], params=["pillar_t", "top_t"], expr=f"pillar {fmt(pillar_t)} mm thick under the cap"),
        dict(id=n("rebate"), kind="dimension", label=f"Rebates under the cap for the hanging sheets ({sfx})", a=None, b=None,
             parts=[n("cap"), n("centre"), n("middle"), n("outer")], params=["top_t", "skin", "gap"],
             expr=f"up to z = {fmt(pin_z)}: a lip of {fmt(height - pin_z)} mm remains above the hanging sheets"),
    ]
    for g in ("front", "back"):
        constraints += [
            dict(id=n(f"gate_{g}"), kind="revolute", label=f"{g.capitalize()} N frame hinge ({sfx}): vertical axis at the pillar",
                 a=n("pillar"), b=n(f"gate_{g}_leg_in"), joint=n(f"gate_{g}"), parts=[n("pillar")] + frame(g),
                 params=["leg", "gate_len", "gate_inset", "pillar_t"],
                 expr=f"hinge corner at x = {fmt(gate_x0)}, y = {fmt((1 if g == 'front' else -1) * gate_y0)}; folds 45 deg from the open pose to lie flat"),
            dict(id=n(f"gate_{g}_frame"), kind="fixed", label=f"{g.capitalize()} N frame: two legs and a diagonal brace ({sfx})",
                 a=n(f"gate_{g}_brace"), b=n(f"gate_{g}_leg_out"), parts=frame(g), params=["brace_w", "brace_t", "gate_len"],
                 expr=f"legs {fmt(gate_len)} mm apart; the brace runs from the top of the hinge leg to the foot of the far leg"),
        ]
total_open = 2 * (eo + 2 * sheet_w + 3 * gap)
constraints += [
    dict(id="dim_open", kind="dimension", label="Open length", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("cap", "centre", "middle", "outer", "filler"))],
         params=["centre_w", "sheet_w", "gap"], expr=f"length = centre_w + 2*(sheet_w+gap) + 4*sheet_w + 6*gap = {fmt(total_open)} mm (dealer: 2800)"),
    dict(id="dim_folded", kind="dimension", label="Folded width", a=None, b=None,
         parts=[p["name"] for p in parts if p["name"].startswith(("cap", "pillar"))], params=["centre_w"],
         expr=f"width = centre_w = {fmt(centre_w)} mm (dealer: 230)"),
    dict(id="dim_filler", kind="dimension", label="Filler sheet", a=None, b=None, parts=["filler"], params=["centre_w", "top_t", "pillar_t", "leg"],
         expr=f"fills the gap of {fmt(2 * f_half)} mm between the hanging centre sheets (folded width less the sheet, pillar and frame stack)"),
    dict(id="dim_leg_height", kind="dimension", label="Leg and pillar height under the top", a=None, b=None,
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
