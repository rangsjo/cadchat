import test from "node:test";
import assert from "node:assert/strict";
import { groupParts, orientation, gridLayout, bedCheck } from "../../tools/static/lib/layout.js";

const part = (name, dx, dy, dz, volume = dx * dy * dz, material = "") => ({ name, volume, material, bbox: [0, 0, 0, dx, dy, dz] });

test("identical parts merge into one group with a quantity", () => {
  const g = groupParts([part("leg_L", 10, 40, 20), part("leg_R", 10, 40, 20), part("rail", 100, 5, 5)]);
  assert.equal(g.length, 2);
  const leg = g.find((x) => x.names.includes("leg_L"));
  assert.equal(leg.qty, 2);
  assert.equal(leg.label, "leg");
});

test("parts rotated differently but the same size still merge", () => {
  assert.equal(groupParts([part("a", 10, 40, 20), part("b", 40, 20, 10)]).length, 1);
});

test("different volume or material keeps parts apart", () => {
  assert.equal(groupParts([part("a", 10, 10, 10), part("b", 10, 10, 10, 900)]).length, 2);
  assert.equal(groupParts([part("a", 10, 10, 10, 1000, "oak"), part("b", 10, 10, 10, 1000, "pine")]).length, 2);
});

test("dims are sorted longest first and the axis order is recorded", () => {
  const [g] = groupParts([part("a", 10, 40, 20)]);
  assert.deepEqual(g.dims, [40, 20, 10]);
  assert.deepEqual(g.order, [1, 2, 0]);
});

test("groups are sorted by footprint, largest first", () => {
  const g = groupParts([part("small", 10, 10, 5), part("big", 100, 50, 5), part("mid", 50, 20, 5)]);
  assert.deepEqual(g.map((x) => x.names[0]), ["big", "mid", "small"]);
});

test("orientation is a proper rotation (det +1) for every axis order", () => {
  const det = (m) => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  for (const o of [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]]) assert.equal(det(orientation(o)), 1, o.join());
});

test("orientation maps the longest source axis to X, the shortest to Z", () => {
  const m = orientation([1, 2, 0]);                  // longest was y, middle z, shortest x
  assert.deepEqual(m[0].map(Math.abs), [0, 1, 0]);
  assert.deepEqual(m[2].map(Math.abs), [1, 0, 0]);
});

test("gridLayout puts the first part at the origin on 100 mm snapped cells", () => {
  const g = groupParts([part("a", 900, 650, 20), part("b", 650, 50, 20), part("c", 600, 50, 20), part("d", 300, 300, 20)]);
  const L = gridLayout(g, { width: 3600 });
  assert.deepEqual([g[0].x, g[0].y], [0, 0]);
  assert.equal(L.pitchX % 100, 0);
  assert.ok(L.pitchX >= 900 + 170);
  assert.equal(L.cols, Math.floor((3600 + 170) / L.pitchX));
  for (const x of g) assert.ok(x.x % L.pitchX === 0 && x.y % 100 === 0);
});

test("gridLayout never lets two cells overlap", () => {
  const g = groupParts(Array.from({ length: 9 }, (_, i) => part("p" + i, 200 + i * 60, 100 + i * 30, 10)));
  gridLayout(g, { width: 1200 });
  for (const a of g) for (const b of g) {
    if (a === b) continue;
    const ox = a.x < b.x + b.dims[0] && b.x < a.x + a.dims[0], oy = a.y < b.y + b.dims[1] && b.y < a.y + a.dims[1];
    assert.ok(!(ox && oy), `${a.names[0]} overlaps ${b.names[0]}`);
  }
});

test("bedCheck flags parts that do not fit the printer bed", () => {
  const groups = groupParts([part("big", 300, 50, 10), part("ok", 200, 200, 10)]);
  const big = groups.find((g) => g.names[0] === "big"), ok = groups.find((g) => g.names[0] === "ok");
  const bed = { x: 220, y: 220, z: 250 };
  assert.equal(bedCheck(big, bed).fits, false);
  assert.match(bedCheck(big, bed).reason, /longest/);
  assert.equal(bedCheck(ok, bed).fits, true);
});

test("bedCheck can turn the part on the bed", () => {
  const [g] = groupParts([part("tall", 50, 240, 10)]);
  assert.equal(bedCheck(g, { x: 100, y: 250, z: 250 }).fits, true);        // turned 90 degrees on the bed
  assert.equal(bedCheck(g, { x: 200, y: 200, z: 250 }).fits, false);
  assert.equal(bedCheck(g, { x: 250, y: 250, z: 5 }).fits, false);          // too tall for the build height
});

import { packPlates } from "../../tools/static/lib/layout.js";

const it = (id, w, h) => ({ id, w, h });
const noOverlap = (items, gap) => items.every((a, i) => items.every((b, j) => i === j || a.x + a.w + gap <= b.x || b.x + b.w + gap <= a.x || a.y + a.h + gap <= b.y || b.y + b.h + gap <= a.y));

test("packPlates puts small parts on one plate inside the bed without overlap", () => {
  const r = packPlates([it("a", 100, 50), it("b", 80, 80), it("c", 60, 60)], { x: 220, y: 220 }, 5);
  assert.equal(r.plates.length, 1);
  assert.deepEqual(r.unplaced, []);
  const items = r.plates[0].items;
  assert.ok(items.every((p) => p.x >= 0 && p.y >= 0 && p.x + p.w <= 220 && p.y + p.h <= 220));
  assert.ok(noOverlap(items, 5));
});

test("packPlates starts a second plate when the first is full", () => {
  const r = packPlates(Array.from({ length: 5 }, (_, i) => it("p" + i, 200, 100)), { x: 220, y: 220 }, 5);
  assert.equal(r.plates.length, 3);                           // two 200x100 parts per plate
  assert.equal(r.plates.flatMap((p) => p.items).length, 5);
});

test("packPlates reports parts that cannot fit any plate", () => {
  const r = packPlates([it("huge", 300, 10), it("ok", 50, 50)], { x: 220, y: 220 }, 5);
  assert.deepEqual(r.unplaced, ["huge"]);
  assert.equal(r.plates[0].items.length, 1);
});

test("packPlates may turn a part to make it fit", () => {
  const r = packPlates([it("long", 240, 50)], { x: 100, y: 250 }, 5);
  assert.deepEqual(r.unplaced, []);
  assert.deepEqual([r.plates[0].items[0].w, r.plates[0].items[0].h, r.plates[0].items[0].turned], [50, 240, true]);
});
