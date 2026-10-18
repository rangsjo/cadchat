"""Render still views (iso, front, side, top) of a mechanism's presets to PNG, no viewer needed (phone friendly).
Usage: python tools/render_views.py parts/folding_table.py [outdir]   -> <outdir>/<preset>.png (2x2 contact sheet per preset)"""
import os
import runpy
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

COL = {"top": (214, 160, 98), "pillar": (150, 98, 62), "board": (200, 150, 95), "leg": (126, 78, 52), "beam": (170, 112, 72), "hardware": (230, 200, 60)}
VIEWS = {"Iso": (-35, 25), "Front": (0, 0), "Side": (90, 0), "Top": (0, 90)}     # (azimuth, elevation) in degrees


def basis(az, el):
    a, e = np.radians(az), np.radians(el)
    right = np.array([np.cos(a), np.sin(a), 0.0])                                 # screen x
    fwd = np.array([-np.sin(a) * np.cos(e), np.cos(a) * np.cos(e), np.sin(e)])    # towards the viewer's eye direction is -fwd... (view dir = fwd)
    up = np.cross(right, fwd)
    up = up if up[2] >= 0 or el == 90 else -up
    if el == 90:
        up = np.array([-np.sin(a) * 0 + 0, 1.0, 0.0]); right = np.array([1.0, 0, 0])
    return right, up, np.cross(right, up)                                         # third = towards the camera


def tris_of(pp):
    out = []
    for name, shape, role in pp:
        v, t = shape.tessellate(1.0, 0.3)
        v = np.array([[p.X, p.Y, p.Z] for p in v])
        for a, b, c in t:
            out.append((v[a], v[b], v[c], role))
    return out


def render(tris, view, size, box):
    right, up, toward = basis(*VIEWS[view])
    pts = np.array([[t[0], t[1], t[2]] for t in tris])                           # n,3,3
    sx, sy, sz = pts @ right, pts @ up, pts @ toward
    mn = np.array([box[0] @ right, box[0] @ up]) if False else None
    corners = np.array([[x, y, z] for x in (box[0][0], box[1][0]) for y in (box[0][1], box[1][1]) for z in (box[0][2], box[1][2])])
    cx, cy = corners @ right, corners @ up
    k = 0.9 * min(size[0] / (cx.max() - cx.min()), size[1] / (cy.max() - cy.min()))
    ox, oy = size[0] / 2 - k * (cx.max() + cx.min()) / 2, size[1] / 2 + k * (cy.max() + cy.min()) / 2
    S = 2
    img = Image.new("RGB", (size[0] * S, size[1] * S), (246, 246, 244))
    d = ImageDraw.Draw(img)
    light = np.array([0.35, -0.5, 0.8]); light /= np.linalg.norm(light)
    depth = sz.mean(axis=1)
    for i in np.argsort(depth):                                                    # painter: far first
        p = pts[i]
        n = np.cross(p[1] - p[0], p[2] - p[0]); ln = np.linalg.norm(n)
        if ln < 1e-9:
            continue
        n /= ln
        if n @ toward < 0:
            n = -n                                                                 # no culling: shells are closed, far faces are drawn first
        shade = 0.55 + 0.45 * max(0.0, float(n @ light))
        base = COL.get(tris[i][3], (170, 170, 170))
        fill = tuple(int(c * shade) for c in base)
        poly = [((ox + k * sx[i][j]) * S, (oy - k * sy[i][j]) * S) for j in range(3)]
        d.polygon(poly, fill=fill, outline=fill)
    return img.resize(size, Image.LANCZOS)


def main(script, outdir="exports/views"):
    os.environ.setdefault("CADCHAT_ROOT", "/tmp/render_views")
    ns = runpy.run_path(script, run_name="render")
    roles = {p["name"]: p.get("role", "") for p in ns["parts"]}
    Path(outdir).mkdir(parents=True, exist_ok=True)
    presets = ns.get("presets") or {"default": {}}
    posed = ns.get("posed") or (lambda vals: [(p["name"], p["shape"]) for p in ns["parts"]])            # a static model has no joints
    for preset, vals in presets.items():
        pp = [(n, s, roles[n]) for n, s in posed(vals)]
        tris = tris_of(pp)
        allv = np.array([t[i] for t in tris for i in range(3)])
        box = (allv.min(axis=0), allv.max(axis=0))
        W, H = 800, 560
        sheet = Image.new("RGB", (W * 2, H * 2), (246, 246, 244))
        for i, view in enumerate(VIEWS):
            sheet.paste(render(tris, view, (W, H), box), ((i % 2) * W, (i // 2) * H))
            ImageDraw.Draw(sheet).text(((i % 2) * W + 12, (i // 2) * H + 10), f"{preset} - {view}", fill=(60, 60, 60))
        sheet.save(f"{outdir}/{preset}.png")
        print(f"{outdir}/{preset}.png")


if __name__ == "__main__":
    main(*sys.argv[1:3])
