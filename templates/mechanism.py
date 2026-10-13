"""Template for a jointed mechanism (a box with a hinged lid). Copy to parts/NAME.py and edit.

Pattern: build every part in its REFERENCE pose, declare joints (axes in that pose), list presets, hand everything to
Mechanism (posing + collision check) and publish. See .claude/skills/cad-mechanism/SKILL.md.
"""
from pathlib import Path
import sys

from build123d import *

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from cadview import load_params, params_out, publish_kinematic
from kinematics import Mechanism

# ---- parameters: name -> (default, unit, group, description). The viewer's Parameters tab overrides them.
PARAMS = {
    "w": (120, "mm", "Box", "Box width (x)"),
    "d": (80, "mm", "Box", "Box depth (y)"),
    "h": (50, "mm", "Box", "Box height (z)"),
    "wall": (4, "mm", "Box", "Wall thickness"),
}
V = load_params(__file__, PARAMS)
w, d, h, wall = V["w"], V["d"], V["h"], V["wall"]

# ---- parts in the reference (closed) pose
body = Box(w, d, h, align=(Align.CENTER, Align.CENTER, Align.MIN)) - \
    Pos(0, 0, wall) * Box(w - 2 * wall, d - 2 * wall, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
lid = Pos(0, 0, h) * Box(w, d, wall, align=(Align.CENTER, Align.CENTER, Align.MIN))

parts = [
    dict(name="body", shape=body, joint=None, role="box", material="plywood"),     # joint = the joint that moves it
    dict(name="lid", shape=lid, joint="lid_hinge", role="lid", material="plywood"),
]
# ---- joints: revolute, origin/axis in the reference pose, degrees. parent = joint that carries this joint.
joints = [dict(name="lid_hinge", label="Lid hinge", group="Lid", parent=None,
               origin=[0, -d / 2, h], axis=[1, 0, 0], min=0, max=110)]
presets = {"closed": {"lid_hinge": 0}, "open": {"lid_hinge": 100}}      # the first preset is the default

constraints = [
    dict(id="hinge", kind="revolute", label="Hinge: body ↔ lid", a="body", b="lid", joint="lid_hinge",
         parts=["body", "lid"], params=["d", "h"], expr=f"axis at the back top edge: y = -d/2 = {-d / 2:g}, z = h = {h:g}"),
    dict(id="dim_h", kind="dimension", label="Overall height", a=None, b=None, parts=["body", "lid"],
         params=["h", "wall"], expr=f"height = h + wall = {h + wall:g} mm"),
]
params_json = params_out(PARAMS, V)


def exempt(a, b):
    return False        # pairs that legitimately touch/overlap (hardware, tenons), e.g. a.startswith("hinge_")


mech = Mechanism(parts, joints, presets, exempt=exempt)
posed, check_pose = mech.posed, mech.check      # check_pose(values) is what the viewer calls on every slider move

if __name__ == "__main__":
    Path("exports").mkdir(exist_ok=True)
    for name, vals in mech.presets.items():
        pp = posed(vals)
        comp = Compound([s for _, s in pp])
        bb = comp.bounding_box()
        hits = check_pose(vals)
        print(f"{name:8s} {bb.size.X:.0f} x {bb.size.Y:.0f} x {bb.size.Z:.0f} mm | collisions: {hits or 'none'}")
        export_step(comp, f"exports/NAME_{name}.step")
    publish_kinematic(parts, joints, mech.presets, "parts/NAME.py", params_json, constraints)
