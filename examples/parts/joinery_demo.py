"""Joinery demo: a small bookcase (dowelled top and bottom, a shelf in dados, a back in rabbets) and a frame (mortise and tenon, half lap).
Shows how tools/joints.py is used: every joint returns both boards cut to fit; the notes feed the cut list and the constraint list."""
import os
import sys
from itertools import combinations
from pathlib import Path

from build123d import *

sys.path.insert(0, str(os.environ.get("CADCHAT_TOOLS") or r"/home/jonas/Private/cad_chat/tools"))
import exchange
import joints as J
from cadview import load_params, params_out, publish_kinematic

PARAMS = {  # name: (default, unit, group, description)
    "width": (600, "mm", "Bookcase", "Outside width"),
    "height": (700, "mm", "Bookcase", "Outside height"),
    "depth": (300, "mm", "Bookcase", "Depth"),
    "t": (18, "mm", "Bookcase", "Board thickness"),
    "shelf_z": (340, "mm", "Bookcase", "Height of the shelf underside"),
    "frame_h": (500, "mm", "Frame", "Height of the frame"),
    "frame_w": (320, "mm", "Frame", "Clear width between the stiles"),
}
V = load_params(__file__, PARAMS)
W, H, D, t, shelf_z = V["width"], V["height"], V["depth"], V["t"], V["shelf_z"]
FH, FW = V["frame_h"], V["frame_w"]


def board(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


boards, hardware, constraints = {}, [], []


def put(j, a, b):
    """Store both boards of a joint (under their names), keep its hardware and add it to the constraint list."""
    boards[a], boards[b] = j.a, j.b
    hardware.extend((f"{a}_{b}_{n}", s) for n, s in j.hardware)
    constraints.append(j.as_constraint(f"{a}_{b}", a, b))


# ---- bookcase --------------------------------------------------------------------------------------------------------------
boards.update(side_L=board(0, t, 0, D, 0, H), side_R=board(W - t, W, 0, D, 0, H), bottom=board(t, W - t, 0, D, 0, t), top=board(t, W - t, 0, D, H - t, H),
              shelf=board(t - 6, W - t + 6, 0, D - 6, shelf_z, shelf_z + t), back=board(t - 6, W - t + 6, D - 6, D, t, H - t))
for side in ("L", "R"):                                                          # top and bottom on dowels
    for rail in ("bottom", "top"):
        put(J.dowel_butt(boards[f"side_{side}"], boards[rail], **{k: v for k, v in J.defaults("dowel_butt", t).items() if k != "edge"}, edge=40),
            f"side_{side}", rail)
for side in ("L", "R"):                                                          # the shelf in dados, the back in rabbets
    put(J.dado(boards[f"side_{side}"], boards["shelf"]), f"side_{side}", "shelf")
    put(J.rabbet(boards[f"side_{side}"], boards["back"]), f"side_{side}", "back")

# ---- frame ------------------------------------------------------------------------------------------------------------------
fx = W + 100                                                                   # beside the bookcase
sw = 45
boards.update(stile_1=board(fx, fx + sw, 0, t, 0, FH), stile_2=board(fx + sw + FW, fx + 2 * sw + FW, 0, t, 0, FH))
rail_len = FW + 2 * 25                                                           # 25 mm tenon into each stile
for name, z in (("rail_top", FH - 60), ("rail_mid", FH / 2 - 30), ("rail_bottom", 0)):
    boards[name] = board(fx + sw - 25, fx + sw + FW + 25, 0, t, z, z + 60)
    d = J.defaults("mortise_tenon", t)
    put(J.mortise_tenon(boards[name], boards["stile_1"], axis="x", shoulder=d["shoulder"]), name, "stile_1")
    put(J.mortise_tenon(boards[name], boards["stile_2"], axis="x", shoulder=d["shoulder"]), name, "stile_2")
boards["muntin"] = board(fx + sw + FW / 2 - 20, fx + sw + FW / 2 + 20, 0, t, 60, FH - 60)
put(J.half_lap(boards["rail_mid"], boards["muntin"], a_on_top=True), "rail_mid", "muntin")

parts = [dict(name=n, shape=s, joint=None, role="board", material="oak") for n, s in boards.items()]
parts += [dict(name=n, shape=s, joint=None, role="hardware", material="beech") for n, s in hardware]


def overlaps():
    """[[a, b, mm3]] of boards that still overlap after all cuts (must be empty), hardware excluded."""
    out = []
    for (an, a), (bn, b) in combinations(boards.items(), 2):
        i = a.intersect(b)
        v = sum(x.volume for x in i.solids()) if i else 0
        if v > 1:
            out.append([an, bn, round(v)])
    return out


if __name__ == "__main__":
    bad = overlaps()
    print(f"{len(boards)} boards, {len(hardware)} dowels, {len(constraints)} joints, overlaps: {bad or 'none'}")
    assert not bad
    for c in constraints[:3]:
        print(" -", c["expr"])
    Path("exports").mkdir(exist_ok=True)
    exchange.export_step_assembly([(p["name"], p["shape"]) for p in parts], "exports/joinery_demo.step", name="joinery_demo")
    publish_kinematic(parts, [], {"default": {}}, "parts/joinery_demo.py", params_out(PARAMS, V), constraints)
