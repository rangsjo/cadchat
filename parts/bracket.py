"""L-bracket with mounting holes (example static part)."""
import sys
from pathlib import Path

from build123d import *

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from cadview import load_params, params_out, publish_kinematic

PARAMS = {  # name: (default, unit, group, description)
    "length": (60, "mm", "Bracket", "Length (x)"),
    "width": (40, "mm", "Bracket", "Depth of the base plate (y)"),
    "thick": (5, "mm", "Bracket", "Plate and wall thickness"),
    "wall_h": (30, "mm", "Bracket", "Wall height above the plate"),
    "hole_d": (5, "mm", "Holes", "Hole diameter"),
    "fillet_r": (3, "mm", "Bracket", "Inside corner fillet"),
}
V = load_params(__file__, PARAMS)
length, width, thick, wall_h, hole_d, fillet_r = (V[k] for k in ("length", "width", "thick", "wall_h", "hole_d", "fillet_r"))

with BuildPart() as bracket:
    Box(length, width, thick, align=(Align.CENTER, Align.CENTER, Align.MIN))                 # base plate
    with Locations((0, -width / 2 + thick / 2, thick)):                                      # wall on the back edge
        Box(length, thick, wall_h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    fillet(bracket.edges().filter_by(Axis.X).filter_by_position(Axis.Z, thick - 0.1, thick + 0.1)
           .filter_by_position(Axis.Y, -width / 2 + thick - 0.1, -width / 2 + thick + 0.1), radius=fillet_r)
    with Locations((-20, 5), (20, 5), (-20, 15), (20, 15)):                                  # mounting holes in the plate
        Hole(radius=hole_d / 2)
    with Locations((-15, -width / 2 + thick, thick + 18), (15, -width / 2 + thick, thick + 18)):   # holes through the wall
        Hole(radius=hole_d / 2, depth=thick)
part = bracket.part

if __name__ == "__main__":
    bb = part.bounding_box()
    print(f"size {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm | volume {part.volume:.1f} mm3")
    assert part.is_valid
    Path("exports").mkdir(exist_ok=True)
    export_step(part, "exports/bracket.step")
    export_stl(part, "exports/bracket.stl")
    publish_kinematic([dict(name="bracket", shape=part, joint=None, role="bracket", material="aluminium")], [], {"default": {}},
                      "parts/bracket.py", params_out(PARAMS, V))
