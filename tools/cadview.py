"""Publish a (jointed) model for the cadchat viewer.

Each script publishes under its own name: .cad/models/<name>/model.json (name defaults to the script's file stem),
so several models can live side by side and the viewer has a model switcher.

parts:   [{"name", "shape", "joint", "role"?, "material"?}]
           base (reference) geometry, mm, z up; joint = name of the joint that moves it, or None;
           role = free-text group used for colouring (default: derived from the name); material = free text for the cut list
joints:  [{"name", "label", "group", "parent", "origin", "axis", "min", "max"}]  revolute, axes in the base frame, degrees
presets: {"open": {joint_name: degrees, ...}, ...}   (use {"default": {}} for a static part)
script:  project-relative path of the script; if it defines check_pose(values) -> [[partA, partB, mm3], ...]
         the viewer uses it for the live collision check (optional)
"""
import array
import base64
import json
import os
import sys
from pathlib import Path


def root():
    """Project root: CADCHAT_ROOT if set (tests, other projects), else the repository this file lives in."""
    return Path(os.environ.get("CADCHAT_ROOT") or Path(__file__).resolve().parent.parent)


def cad_dir():
    return root() / ".cad"


def model_dir(name):
    return cad_dir() / "models" / name


def load_params(script_file, params):
    """params: {name: (default, unit, group, description)} -> {name: float}, with overrides edited in the viewer."""
    f = model_dir(Path(script_file).stem) / "params.json"
    over = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    return {k: float(over.get(k, d[0])) for k, d in params.items()}


def params_out(params, values):
    return [dict(name=k, value=values[k], default=d[0], unit=d[1], group=d[2], desc=d[3]) for k, d in params.items()]


def _b64(typecode, values):
    """Little-endian binary, base64 encoded: about a third of the size of a JSON number list and much faster to parse."""
    a = array.array(typecode, values)
    if sys.byteorder == "big":
        a.byteswap()
    return base64.b64encode(a.tobytes()).decode()


def publish_kinematic(parts, joints, presets, script, params=None, constraints=None, name=None, tolerance=0.5):
    name = name or Path(script).stem
    items = []
    for p in parts:
        shape = p["shape"]
        verts, tris = shape.tessellate(tolerance, 0.3)
        bb = shape.bounding_box()
        items.append({
            "name": p["name"], "joint": p.get("joint"), "role": p.get("role"), "material": p.get("material"),
            "volume": round(shape.volume, 1),
            "bbox": [round(v, 1) for v in (bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z)],
            "v64": _b64("f", (c for q in verts for c in (q.X, q.Y, q.Z))),
            "t64": _b64("I", (i for tri in tris for i in tri)),
        })
    d = model_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "script").write_text(script, encoding="utf-8")
    tmp = d / "model.tmp"
    tmp.write_text(json.dumps({"name": name, "parts": items, "joints": joints, "presets": presets,
                               "params": params or [], "constraints": constraints or [], "default": next(iter(presets))},
                              separators=(",", ":")), encoding="utf-8")
    tmp.replace(d / "model.json")
    print(f"published '{name}': {len(items)} parts, {len(joints)} joints, {len(presets)} presets")
