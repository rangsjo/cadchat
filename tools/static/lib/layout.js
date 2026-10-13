// Manufacturing layout: group identical parts, orient them flat, place them on a snapped grid, check printer beds.
import { stem } from "./roles.js";

const parity = (p) => { let inv = 0; for (let a = 0; a < 3; a++) for (let b = a + 1; b < 3; b++) if (p[a] > p[b]) inv++; return inv % 2 ? -1 : 1; };

/** Rows map source axes to (x, y, z) = (longest, middle, shortest side); the sign keeps it a rotation (det +1). */
export function orientation([i0, i1, i2]) {
  const m = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  m[0][i0] = 1; m[1][i1] = 1; m[2][i2] = parity([i0, i1, i2]);
  return m;
}

export function groupParts(parts) {
  const by = new Map();
  for (const p of parts) {
    const b = p.bbox, dims = [b[3] - b[0], b[4] - b[1], b[5] - b[2]];
    const order = [0, 1, 2].sort((i, j) => dims[j] - dims[i] || i - j);
    const sorted = order.map((i) => dims[i]);
    const sig = sorted.map((d) => d.toFixed(1)).join("x") + "|" + (p.volume / 100).toFixed(0) + "|" + (p.material || "");
    if (!by.has(sig)) by.set(sig, { part: p, names: [], qty: 0, dims: sorted, order, bbox: b, material: p.material || "" });
    const g = by.get(sig);
    g.names.push(p.name); g.qty++;
  }
  const groups = [...by.values()];
  for (const g of groups) g.label = [...new Set(g.names.map(stem))].join(" / ");
  return groups.sort((a, b) => b.dims[0] * b.dims[1] - a.dims[0] * a.dims[1]);
}

/** Regular grid: one column pitch for all, row pitch from the widest part of the row, everything snapped. */
export function gridLayout(groups, { width = 3600, snap = 100, room = 170, rowRoom = 190 } = {}) {
  const up = (v) => Math.ceil(v / snap) * snap;
  const pitchX = up(Math.max(0, ...groups.map((g) => g.dims[0])) + room);
  const cols = Math.max(1, Math.floor((width + room) / pitchX));
  const rows = [0];
  for (let r = 0; r * cols < groups.length; r++) {
    const rowW = Math.max(...groups.slice(r * cols, (r + 1) * cols).map((g) => g.dims[1]));
    rows.push(rows[r] + up(rowW + rowRoom));
  }
  groups.forEach((g, i) => { g.col = i % cols; g.row = Math.floor(i / cols); g.x = g.col * pitchX; g.y = rows[g.row]; });
  return { cols, pitchX, rows, extent: { x: cols * pitchX, y: rows[rows.length - 1] } };
}

/** Does the part fit a printer bed {x, y, z} lying flat (turning it in the plane is allowed)? */
export function bedCheck(g, bed) {
  const [L, W, T] = g.dims;
  const flat = (L <= bed.x && W <= bed.y) || (L <= bed.y && W <= bed.x);
  if (T > bed.z) return { fits: false, reason: `height ${T.toFixed(0)} mm exceeds the build height ${bed.z} mm` };
  if (!flat) return { fits: false, reason: `longest side ${L.toFixed(0)} mm and width ${W.toFixed(0)} mm do not fit the ${bed.x} x ${bed.y} mm bed` };
  return { fits: true, reason: "" };
}

/** Shelf-pack items {id, w, h} onto printer plates {x, y}; turns a part 90 degrees if only that fits. */
export function packPlates(items, bed, gap = 5) {
  const plates = [], unplaced = [];
  const fits = (w, h) => w <= bed.x && h <= bed.y;
  const sorted = items.map((i) => ({ ...i })).sort((a, b) => Math.max(b.w, b.h) - Math.max(a.w, a.h));
  for (const it of sorted) {
    let { w, h } = it, turned = false;
    if (!fits(w, h)) { if (fits(h, w)) { [w, h] = [h, w]; turned = true; } else { unplaced.push(it.id); continue; } }
    let placed = false;
    for (const pl of plates) {
      const row = pl.rows.find((r) => r.x + w <= bed.x && h <= r.h);
      if (row) { pl.items.push({ id: it.id, x: row.x, y: row.y, w, h, turned }); row.x += w + gap; placed = true; break; }
      const y = pl.rows.length ? pl.rows[pl.rows.length - 1].y + pl.rows[pl.rows.length - 1].h + gap : 0;
      if (y + h <= bed.y) { pl.rows.push({ y, h, x: w + gap }); pl.items.push({ id: it.id, x: 0, y, w, h, turned }); placed = true; break; }
    }
    if (!placed) plates.push({ rows: [{ y: 0, h, x: w + gap }], items: [{ id: it.id, x: 0, y: 0, w, h, turned }] });
  }
  return { plates: plates.map(({ items }) => ({ items })), unplaced };
}
