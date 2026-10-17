"""Shaft with a closed keyway (example static part). Keyway per DIN 6885 / ISO 773 for d = 17..22: key 6x6, depth t1 = 3.5."""
import sys
from pathlib import Path

from build123d import *

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import exchange
from cadview import load_params, params_out, publish_kinematic

PARAMS = {  # name: (default, unit, group, description)
    "length": (100, "mm", "Shaft", "Overall length"),
    "dia": (20, "mm", "Shaft", "Diameter"),
    "end_chamfer": (1, "mm", "Shaft", "Chamfer on both ends"),
    "key_w": (6, "mm", "Keyway", "Keyway width"),
    "key_depth": (3.5, "mm", "Keyway", "Keyway depth in the shaft"),
    "key_len": (40, "mm", "Keyway", "Keyway length"),
    "key_offset": (12, "mm", "Keyway", "Distance from the shaft end to the keyway start"),
}
V = load_params(__file__, PARAMS)
length, dia, end_chamfer = V["length"], V["dia"], V["end_chamfer"]
key_w, key_depth, key_len, key_offset = V["key_w"], V["key_depth"], V["key_len"], V["key_offset"]
r = dia / 2

with BuildPart() as shaft:
    Cylinder(radius=r, height=length, align=(Align.CENTER, Align.CENTER, Align.MIN))
    chamfer(shaft.edges().filter_by(GeomType.CIRCLE), length=end_chamfer)
    plain_volume = shaft.part.volume
    # closed keyway with rounded ends (end mill), cut into the +X side
    with BuildSketch(Plane.YZ.offset(r - key_depth)):
        with Locations((0, key_offset + key_len / 2)):
            SlotOverall(key_len, key_w, rotation=90)
    extrude(amount=key_depth + 1, mode=Mode.SUBTRACT)
part = shaft.part

if __name__ == "__main__":
    bb = part.bounding_box()
    print(f"size {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm | volume {part.volume:.1f} mm3 | keyway removed {plain_volume - part.volume:.1f} mm3")
    assert part.is_valid
    Path("exports").mkdir(exist_ok=True)
    exchange.export_step_assembly([("shaft", part)], "exports/shaft.step", name="shaft")
    export_stl(part, "exports/shaft.stl")
    publish_kinematic([dict(name="shaft", shape=part, joint=None, role="shaft", material="steel")], [], {"default": {}},
                      "parts/shaft.py", params_out(PARAMS, V))
