"""Template for a single static part. Copy to parts/NAME.py and edit."""
from pathlib import Path
import sys

from build123d import *

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from cadview import publish_kinematic

# Parameters (mm): keep every dimension here so it can be changed in one line.
length, width, thick = 100, 60, 8
hole_d = 6

with BuildPart() as p:
    Box(length, width, thick)
    with Locations((-30, 0), (30, 0)):
        Hole(radius=hole_d / 2)
part = p.part

if __name__ == "__main__":
    bb = part.bounding_box()
    print(f"size {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm | volume {part.volume / 1000:.1f} cm3")
    assert part.is_valid, "invalid solid"
    Path("exports").mkdir(exist_ok=True)
    export_step(part, "exports/NAME.step")
    export_stl(part, "exports/NAME.stl")
    publish_kinematic([dict(name="NAME", shape=part, joint=None)], [], {"default": {}}, "parts/NAME.py")
