"""Import and export for exchanging parts with other CAD systems (Creo, SolidWorks, Fusion, FreeCAD, slicers).

STEP assemblies keep part names and the assembly tree; STL and 3MF are meshes for printing and visualisation.
"""
import copy
import re
import struct
from pathlib import Path

from build123d import Compound, Mesher, export_step, export_stl, import_step, import_stl

import cadview

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
STEP_EXT, MESH_EXT = {".step", ".stp"}, {".stl"}


def _labelled(name, shape):
    c = copy.copy(shape)                  # never rename the caller's shape
    c.label = name
    return c


# ---- export -----------------------------------------------------------------------------------------------------
def export_step_assembly(named_shapes, path, name="assembly"):
    """One STEP product per part under a named top assembly, so other CAD systems show a proper tree with names."""
    asm = Compound(label=name, children=[_labelled(n, s) for n, s in named_shapes])
    export_step(asm, str(path))
    return Path(path)


def export_stl_parts(named_shapes, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    out = []
    for n, s in named_shapes:
        f = directory / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', n)}.stl"
        export_stl(s, str(f))
        out.append(f)
    return out


def export_3mf(named_shapes, path):
    m = Mesher()
    for n, s in named_shapes:
        m.add_shape(_labelled(n, s), part_number=n)
    m.write(str(path))
    return Path(path)


def model_to_stl(model_name, out):
    """All parts of a published model (reference pose) as one binary STL, straight from the published mesh."""
    import base64
    m = __import__("json").loads((cadview.model_dir(model_name) / "model.json").read_text(encoding="utf-8"))
    tris = []
    for p in m["parts"]:
        v = struct.unpack(f"<{len(base64.b64decode(p['v64'])) // 4}f", base64.b64decode(p["v64"]))
        t = struct.unpack(f"<{len(base64.b64decode(p['t64'])) // 4}I", base64.b64decode(p["t64"]))
        tris += [[v[3 * i:3 * i + 3] for i in t[k:k + 3]] for k in range(0, len(t), 3)]
    buf = bytearray(80) + struct.pack("<I", len(tris))
    for a, b, c in tris:
        u, w = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
        ln = sum(x * x for x in n) ** 0.5
        n = [x / ln for x in n] if ln > 1e-12 else [0, 0, 0]
        buf += struct.pack("<12fH", *n, *a, *b, *c, 0)
    Path(out).write_bytes(bytes(buf))
    return Path(out)


# ---- import -----------------------------------------------------------------------------------------------------
def import_parts(path):
    """[(name, shape)] from a STEP (names and nested assemblies kept, nesting becomes dotted names) or STL file."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in MESH_EXT:
        return [(path.stem, import_stl(str(path)))]
    if ext not in STEP_EXT:
        raise ValueError(f"unsupported file type '{ext}' (use .step, .stp or .stl)")
    root = import_step(str(path))
    leaves = []

    def walk(shape, prefix):
        if shape.children:
            nested = prefix + (shape.label + "." if shape.label and prefix is not None and shape is not root else "")
            for c in shape.children:
                walk(c, nested)
        else:
            leaves.append((prefix + (shape.label or ""), shape))

    walk(root, "")
    if len(leaves) == 1 and leaves[0][1] is root and len(root.solids()) > 1:       # flat compound of unnamed solids
        leaves = [("", s) for s in root.solids()]
    names, seen = [], {}
    for i, (n, s) in enumerate(leaves, 1):
        n = n or (path.stem if len(leaves) == 1 else f"{path.stem}_{i}")
        seen[n] = seen.get(n, 0) + 1
        names.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return list(zip(names, [s for _, s in leaves]))


def import_to_model(path, name=None):
    """Import a file and publish it as a static model, so it can be viewed, measured, sectioned and laid out."""
    path = Path(path)
    name = name or re.sub(r"[^A-Za-z0-9_-]", "_", path.stem).lstrip("_-") or "import"
    if not NAME_RE.match(name):
        raise ValueError("model name must be letters, digits, _ or - (max 64)")
    parts = import_parts(path)
    cadview.publish_kinematic([dict(name=n, shape=s, joint=None) for n, s in parts], [], {"default": {}}, "", name=name)
    return name
