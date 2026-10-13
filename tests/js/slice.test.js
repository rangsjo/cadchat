import test from "node:test";
import assert from "node:assert/strict";
import { sliceLoops, loopArea } from "../../tools/static/lib/slice.js";

// cube [-1,1]^3 as an indexed triangle mesh
const cube = () => {
  const positions = new Float32Array([-1, -1, -1, 1, -1, -1, 1, 1, -1, -1, 1, -1, -1, -1, 1, 1, -1, 1, 1, 1, 1, -1, 1, 1]);
  const index = new Uint32Array([0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 2, 3, 7, 2, 7, 6, 1, 2, 6, 1, 6, 5, 3, 0, 4, 3, 4, 7]);
  return { positions, index };
};
const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
const translate = (x, y, z) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1];   // column-major, like three.js

test("slicing a cube gives one closed outline with the area of its cross section", () => {
  for (const axis of [0, 1, 2]) {
    const loops = sliceLoops(cube(), I, axis, 0.5);
    assert.equal(loops.length, 1, `axis ${axis}`);
    assert.ok(Math.abs(Math.abs(loopArea(loops[0], axis)) - 4) < 1e-6, `area axis ${axis}`);
  }
});

test("the outline lies in the slicing plane", () => {
  const [loop] = sliceLoops(cube(), I, 2, 0.25);
  for (const p of loop) assert.ok(Math.abs(p[2] - 0.25) < 1e-6);
});

test("the mesh matrix is applied before slicing", () => {
  assert.equal(sliceLoops(cube(), translate(0, 0, 10), 2, 0.5).length, 0);
  assert.equal(sliceLoops(cube(), translate(0, 0, 10), 2, 10.5).length, 1);
});

test("a plane outside the part gives no outline", () => {
  assert.deepEqual(sliceLoops(cube(), I, 0, 5), []);
});

test("a plane through a vertex or edge does not crash", () => {
  assert.doesNotThrow(() => sliceLoops(cube(), I, 2, 1));
  assert.doesNotThrow(() => sliceLoops(cube(), I, 2, -1));
});
