import test from "node:test";
import assert from "node:assert/strict";
import { defaultPlanes, clipPlane, storageKey } from "../../tools/static/lib/planes.js";

test("default planes pass through the middle of the model, one per axis", () => {
  const p = defaultPlanes({ min: [-10, -20, 0], max: [30, 20, 10] });
  assert.deepEqual(p.map((x) => x.axis), [0, 1, 2]);
  assert.deepEqual(p.map((x) => x.pos), [10, 0, 5]);
  assert.ok(p.every((x) => x.show && !x.clip));
  assert.equal(new Set(p.map((x) => x.id)).size, 3);
});

test("clip plane keeps the low side by default and the high side when flipped", () => {
  assert.deepEqual(clipPlane({ axis: 1, pos: 3, flip: false }), { normal: [0, -1, 0], constant: 3 });
  assert.deepEqual(clipPlane({ axis: 2, pos: 3, flip: true }), { normal: [0, 0, 1], constant: -3 });
});

test("clip plane discards exactly the far side", () => {
  const { normal, constant } = clipPlane({ axis: 0, pos: 5, flip: false });
  const d = (x) => normal[0] * x + constant;           // >= 0 is kept
  assert.ok(d(4) > 0 && d(6) < 0);
});

test("planes are stored per model", () => {
  assert.notEqual(storageKey("table"), storageKey("bracket"));
  assert.match(storageKey("table"), /table/);
});
