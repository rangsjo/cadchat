// Pure helpers of the workshop sheet (the static page made by tools/share.py). They are inlined into that page, so it works offline.
export function formatMm(v) {
  const a = Math.abs(v);
  if (a >= 100) return String(Math.round(a));
  const r = Math.round(a * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

export function dist(a, b) {
  const dx = Math.abs(b[0] - a[0]), dy = Math.abs(b[1] - a[1]);
  return { d: Math.hypot(dx, dy), dx, dy };
}

export function nearest(pts, p, radius) {
  let best = null, bd = radius;
  for (let i = 0; i + 1 < pts.length; i += 2) {
    const d = Math.hypot(pts[i] - p[0], pts[i + 1] - p[1]);
    if (d <= bd) { bd = d; best = [pts[i], pts[i + 1]]; }
  }
  return best;
}

/** Screen transform for a drawing with y up: screen = (tx + scale x, ty - scale y). box = [x0, y0, x1, y1] in mm. */
export function fitView(box, w, h, pad = 24) {
  const bw = box[2] - box[0], bh = box[3] - box[1];
  const scale = bw > 0 && bh > 0 ? Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh) : bw > 0 ? (w - 2 * pad) / bw : bh > 0 ? (h - 2 * pad) / bh : 1;
  const cx = (box[0] + box[2]) / 2, cy = (box[1] + box[3]) / 2;
  return { scale, tx: w / 2 - scale * cx, ty: h / 2 + scale * cy };
}

export function pointInTri(p, a, b, c) {
  const s = (u, v, w) => (u[0] - w[0]) * (v[1] - w[1]) - (v[0] - w[0]) * (u[1] - w[1]);
  const d1 = s(p, a, b), d2 = s(p, b, c), d3 = s(p, c, a);
  const neg = d1 < 0 || d2 < 0 || d3 < 0, pos = d1 > 0 || d2 > 0 || d3 > 0;
  return !(neg && pos);
}

/** tris: rows of 7 numbers [part, x1, y1, x2, y2, x3, y3], far to near. Returns the part under p (the last row that contains it) or -1. */
export function pickPart(tris, p) {
  for (let i = tris.length - 7; i >= 0; i -= 7) {
    if (pointInTri(p, [tris[i + 1], tris[i + 2]], [tris[i + 3], tris[i + 4]], [tris[i + 5], tris[i + 6]])) return tris[i];
  }
  return -1;
}

/** parts: [{name, role, material, size: [x, y, z]}] -> rows {names, qty, size (long to short), role, material}, biggest first. */
export function cutList(parts) {
  const rows = new Map();
  for (const p of parts) {
    const size = [...p.size].map((v) => Math.round(v * 10) / 10).sort((a, b) => b - a);
    const key = [p.role, p.material, ...size].join("|");
    const r = rows.get(key) ?? { names: [], qty: 0, size, role: p.role, material: p.material };
    r.names.push(p.name);
    r.qty += 1;
    rows.set(key, r);
  }
  const vol = (r) => r.size[0] * r.size[1] * r.size[2];
  return [...rows.values()].sort((a, b) => vol(b) - vol(a));
}
