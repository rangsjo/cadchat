"""The workshop site: static, self-contained HTML pages made from the published models (.cad/models/<id>/model.json).

One page per model with flat views (front, side, top, iso) of every preset, overall and part dimensions, tap-to-measure between corners,
a cut list and the joints, plus an index. Everything is inline (no CDN, no images), so a phone in the workshop only needs a browser:
open the file, serve the folder (`cadchat share --serve`) or publish it anywhere that serves static files.

Geometry is posed here with numpy (revolute, sliding and coupled joints, as in tools/kinematics.py and the viewer), projected to the
chosen view, depth sorted and stored as integer tenths of a millimetre; the page draws it on a canvas.
"""
import base64
import html
import json
import re
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
VIEWS = ("front", "side", "top", "iso")
LIGHT = np.array([0.35, -0.5, 0.8]) / np.linalg.norm([0.35, -0.5, 0.8])
FEATURE_DEG = 30.0


def _basis(view):
    """(right, up, toward the viewer) in world coordinates, orthonormal and right handed."""
    if view == "front":
        return np.array([1.0, 0, 0]), np.array([0, 0, 1.0]), np.array([0, -1.0, 0])
    if view == "side":
        return np.array([0, 1.0, 0]), np.array([0, 0, 1.0]), np.array([1.0, 0, 0])
    if view == "top":
        return np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])
    t = np.array([-1.0, -1.3, 1.0])
    t /= np.linalg.norm(t)
    r = np.cross([0, 0, 1.0], t)
    r /= np.linalg.norm(r)
    return r, np.cross(t, r), t


def load_model(root, mid):
    return json.loads((Path(root) / ".cad" / "models" / mid / "model.json").read_text(encoding="utf-8"))


def _decode(part):
    v = np.frombuffer(base64.b64decode(part["v64"]), dtype="<f4").astype(float).reshape(-1, 3)
    t = np.frombuffer(base64.b64decode(part["t64"]), dtype="<u4").astype(int).reshape(-1, 3)
    return v, t


def _interp(table, x):
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def _joint_matrix(j, value):
    m = np.eye(4)
    if j.get("type") == "prismatic":
        a = np.array(j["axis"], float)
        m[:3, 3] = a / np.linalg.norm(a) * value
        return m
    a = np.array(j["axis"], float)
    a /= np.linalg.norm(a)
    th = np.radians(value)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    r = np.eye(3) + np.sin(th) * k + (1 - np.cos(th)) * (k @ k)
    o = np.array(j["origin"], float)
    m[:3, :3] = r
    m[:3, 3] = o - r @ o
    return m


def posed_parts(model, values):
    """[(name, world vertices (n, 3), triangles (m, 3))] in the pose given by joint values (mimic joints follow their drivers)."""
    jmap = {j["name"]: j for j in model["joints"]}
    vals = {n: float(values.get(n, 0)) for n in jmap}
    for n, j in jmap.items():
        if j.get("mimic"):
            vals[n] = _interp(j["mimic"]["table"], vals.get(j["mimic"]["of"], 0.0))
    out = []
    for p in model["parts"]:
        v, t = _decode(p)
        m = np.eye(4)
        j = p.get("joint")
        while j:                                              # M = R_parent ... R_leaf
            m = _joint_matrix(jmap[j], vals[j]) @ m
            j = jmap[j].get("parent")
        out.append((p["name"], v @ m[:3, :3].T + m[:3, 3], t))
    return out


def _feature_mask(v, t):
    """For every triangle a 3-bit mask of the edges worth drawing: boundary of a face or a crease sharper than FEATURE_DEG."""
    n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    n = n / np.where(ln == 0, 1, ln)[:, None]
    edges = {}
    for i, (a, b, c) in enumerate(t):
        for k, (p, q) in enumerate(((a, b), (b, c), (c, a))):
            edges.setdefault((min(p, q), max(p, q)), []).append((i, k))
    mask = np.zeros(len(t), int)
    cos = np.cos(np.radians(FEATURE_DEG))
    for users in edges.values():
        if len(users) != 2 or float(n[users[0][0]] @ n[users[1][0]]) < cos:
            for i, k in users:
                mask[i] |= 1 << k
    return mask


def _box_mesh(lo, hi):
    """The 12 triangles of an axis-aligned box: small hardware (hinge barrels, dowels) is drawn as its box to keep the pages light."""
    c = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
    t = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return c, t


def scene(model, values, view):
    """{"parts": [{name, size, min}], "bbox": [x0, y0, x1, y1] (view plane, 0.1 mm), "tris": flat ints}, far to near.
    A triangle is 8 numbers: part index, x1, y1, x2, y2, x3, y3, code (shade 0..9 + 16 x mask of the edges to draw)."""
    right, up, toward = _basis(view)
    posed = posed_parts(model, values)
    rows, meta = [], []
    roles = [p.get("role") for p in model["parts"]]
    for i, (name, v, t) in enumerate(posed):
        lo, hi = v.min(axis=0), v.max(axis=0)
        if roles[i] == "hardware":
            v, t = _box_mesh(lo, hi)
        meta.append({"name": name, "size": [round(float(x), 1) for x in hi - lo], "min": [round(float(x), 1) for x in lo]})
        if not len(t):
            continue
        s = np.stack([v @ right, v @ up, v @ toward], axis=1)
        n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
        ln = np.linalg.norm(n, axis=1)
        n = n / np.where(ln == 0, 1, ln)[:, None]
        facing = np.where((n @ toward) < 0, -1.0, 1.0)[:, None]
        shade = np.clip(np.round((0.45 + 0.55 * np.maximum(0, (n * facing) @ LIGHT)) * 9), 0, 9).astype(int)
        mask = _feature_mask(v, t)
        depth = s[t][:, :, 2].mean(axis=1)
        for k in range(len(t)):
            xy = s[t[k]][:, :2]
            area = (xy[1, 0] - xy[0, 0]) * (xy[2, 1] - xy[0, 1]) - (xy[2, 0] - xy[0, 0]) * (xy[1, 1] - xy[0, 1])
            if abs(area) < 1e-6 and not mask[k]:
                continue
            rows.append((depth[k], i, xy, shade[k] + 16 * mask[k]))
    rows.sort(key=lambda r: r[0])
    flat = []
    xs, ys = [], []
    for _, i, xy, code in rows:
        q = np.round(xy * 10).astype(int)
        flat += [i, *q.ravel().tolist(), int(code)]
        xs += q[:, 0].tolist()
        ys += q[:, 1].tolist()
    bbox = [min(xs), min(ys), max(xs), max(ys)] if xs else [0, 0, 0, 0]
    return {"parts": meta, "bbox": bbox, "tris": flat}


def cut_rows(model):
    return [{"name": p["name"], "role": p.get("role") or "", "material": p.get("material") or "", "volume": p.get("volume", 0)} for p in model["parts"]]


def _sheet_js():
    src = (HERE / "static" / "lib" / "sheet.js").read_text(encoding="utf-8")
    return re.sub(r"^export ", "", src, flags=re.M)


def model_page(model, mid):
    poses = {name: {k: v for k, v in vals.items()} for name, vals in model["presets"].items()}
    scenes, sizes = {}, {}
    for pose, vals in poses.items():
        scenes[pose] = {}
        for view in VIEWS:
            s = scene(model, vals, view)
            scenes[pose][view] = {"tris": s["tris"], "bbox": s["bbox"]}
            if view == "front":
                sizes[pose] = s["parts"]
    data = {"name": model.get("name", mid), "default": model.get("default") or next(iter(poses)), "parts": cut_rows(model), "poses": sizes, "scenes": scenes,
            "constraints": [{"label": c.get("label", c.get("id", "")), "expr": c.get("expr", ""), "kind": c.get("kind", "")} for c in model.get("constraints", [])],
            "params": [{"name": p["name"], "value": p["value"], "unit": p.get("unit", ""), "desc": p.get("desc", "")} for p in model.get("params", [])]}
    text = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    tpl = (HERE / "sheet_template.html").read_text(encoding="utf-8")
    return tpl.replace("__TITLE__", html.escape(mid)).replace("__DATA__", text).replace("__SHEETJS__", _sheet_js())


def index_page(entries):
    items = "".join(f'<a class="card" href="{html.escape(mid)}.html"><b>{html.escape(mid)}</b><small>{n} parts · {len(m["presets"])} poses</small></a>'
                    for mid, m, n in entries)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Workshop sheets</title><style>body{{margin:0;font:16px system-ui,sans-serif;background:#f4f4f2;color:#222}}'
            f'h1{{font-size:20px;margin:0;padding:16px}}.card{{display:block;margin:10px 16px;padding:16px;background:#fff;border-radius:12px;'
            f'text-decoration:none;color:inherit;box-shadow:0 1px 3px #0002}}.card small{{display:block;color:#777;margin-top:4px}}</style></head>'
            f'<body><h1>Workshop sheets</h1>{items or "<p style=margin:16px>No models yet.</p>"}</body></html>')


def build_site(root, outdir, models=None):
    root, out = Path(root), Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    ids = sorted(p.parent.name for p in (root / ".cad" / "models").glob("*/model.json"))
    if models is not None:
        ids = [i for i in ids if i in models]
    written, entries = [], []
    for mid in ids:
        m = load_model(root, mid)
        if not m.get("parts"):
            continue
        f = out / f"{mid}.html"
        f.write_text(model_page(m, mid), encoding="utf-8")
        written.append(f)
        entries.append((mid, m, len(m["parts"])))
    idx = out / "index.html"
    idx.write_text(index_page(entries), encoding="utf-8")
    return written + [idx] if models is None or written else [idx]
