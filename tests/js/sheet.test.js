import test from "node:test";
import assert from "node:assert/strict";
import { formatMm, dist, nearest, fitView, pointInTri, pickPart, cutList } from "../../tools/static/lib/sheet.js";

test("lengths read like a workshop drawing: whole mm, one decimal under 100", () => {
  assert.equal(formatMm(2798.04), "2798");
  assert.equal(formatMm(230), "230");
  assert.equal(formatMm(18.04), "18");
  assert.equal(formatMm(7.25), "7.3");
  assert.equal(formatMm(0.4), "0.4");
  assert.equal(formatMm(-12.6), "12.6");                           // always a length
});

test("distance between two tapped points with its parts along the view axes", () => {
  assert.deepEqual(dist([0, 0], [300, 400]), { d: 500, dx: 300, dy: 400 });
  assert.deepEqual(dist([10, 10], [10, 10]), { d: 0, dx: 0, dy: 0 });
});

test("nearest snaps to the closest corner within the radius, else nothing", () => {
  const pts = [0, 0, 100, 0, 100, 50];
  assert.deepEqual(nearest(pts, [98, 3], 10), [100, 0]);
  assert.deepEqual(nearest(pts, [60, 60], 10), null);
  assert.deepEqual(nearest([], [0, 0], 10), null);
  assert.deepEqual(nearest(pts, [99, 49], 10), [100, 50]);
});

test("fitView centres the drawing in the screen with a margin and flips y", () => {
  const v = fitView([0, 0, 200, 100], 400, 300, 20);
  assert.equal(v.scale, 1.8);                                      // (400 - 40) / 200
  assert.equal(v.tx, 20);
  assert.equal(v.ty, 150 + 90);                                    // centre y = 150, drawing is 100 high: bottom edge at 150 + 90 (y up)
  const b = fitView([-50, -50, 50, 50], 200, 600, 0);
  assert.equal(b.scale, 2);
  assert.equal(fitView([0, 0, 0, 0], 100, 100, 10).scale, 1);      // a point does not divide by zero
});

test("point in triangle works for either winding", () => {
  assert.ok(pointInTri([1, 1], [0, 0], [4, 0], [0, 4]));
  assert.ok(pointInTri([1, 1], [0, 0], [0, 4], [4, 0]));
  assert.ok(!pointInTri([3, 3], [0, 0], [4, 0], [0, 4]));
});

test("picking returns the part drawn last (nearest the viewer) under the tap", () => {
  // rows of 7 numbers: part, x1,y1, x2,y2, x3,y3
  const tris = [0, 0, 0, 10, 0, 0, 10, 1, 2, 2, 8, 2, 2, 8];
  assert.equal(pickPart(tris, [3, 3]), 1);
  assert.equal(pickPart(tris, [8, 1]), 0);
  assert.equal(pickPart(tris, [30, 30]), -1);
  assert.equal(pickPart([], [1, 1]), -1);
});

test("cut list groups identical boards and sorts the sides long to short", () => {
  const rows = cutList([
    { name: "leg_1", role: "leg", material: "oak", size: [18, 45, 700] },
    { name: "leg_2", role: "leg", material: "oak", size: [45, 18, 700] },
    { name: "top", role: "top", material: "oak", size: [900, 600, 22] },
    { name: "dowel_1", role: "hardware", material: "beech", size: [6, 6, 19.6] },
  ]);
  const leg = rows.find((r) => r.names.includes("leg_1"));
  assert.deepEqual(leg.size, [700, 45, 18]);
  assert.equal(leg.qty, 2);
  assert.deepEqual(rows.map((r) => r.names[0]), ["top", "leg_1", "dowel_1"]);       // biggest first
});
