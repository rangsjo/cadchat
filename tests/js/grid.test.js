import test from "node:test";
import assert from "node:assert/strict";
import { gridSpec } from "../../tools/static/lib/grid.js";

test("a table-sized model gets a 100 mm floor grid with 500 mm lines", () => {
  const g = gridSpec({ min: [-1400, -450, 0], max: [1400, 450, 739] });
  assert.equal(g.cell, 100);
  assert.equal(g.major, 500);
  assert.equal(g.z, 0);
  assert.ok(g.size >= 2800 * 1.3 && g.size % (2 * g.major) === 0);
  assert.equal(g.label, "grid 100 mm");
});

test("small parts get a finer grid and big ones a coarser one, never more than ~80 cells across", () => {
  const small = gridSpec({ min: [0, 0, 0], max: [100, 60, 20] });
  assert.equal(small.cell, 10);
  const big = gridSpec({ min: [0, 0, 0], max: [20000, 8000, 3000] });
  assert.ok(big.cell >= 500);
  for (const g of [small, big]) assert.ok(g.size / g.cell <= 200);
});

test("the floor follows a model that sinks below zero and stays at zero otherwise", () => {
  assert.equal(gridSpec({ min: [0, 0, 20], max: [10, 10, 30] }).z, 0);
  assert.equal(gridSpec({ min: [0, 0, -50], max: [10, 10, 30] }).z, -50);
});

test("an empty or missing box still gives a usable grid", () => {
  const g = gridSpec(null);
  assert.ok(g.cell > 0 && g.size > 0 && g.z === 0);
});
