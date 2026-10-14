import test from "node:test";
import assert from "node:assert/strict";
import { toAsciiStl } from "../../tools/static/lib/stl.js";

const tri = { positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), index: new Uint32Array([0, 1, 2]) };
const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];

test("writes one facet per triangle with a unit normal", () => {
  const s = toAsciiStl("t", [{ ...tri, matrix: I }]);
  assert.match(s, /^solid t\n/);
  assert.equal((s.match(/facet normal/g) || []).length, 1);
  assert.match(s, /facet normal 0 0 1/);
  assert.match(s, /endsolid t\s*$/);
});

test("the mesh matrix is applied to the vertices", () => {
  const T = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 20, 30, 1];
  assert.match(toAsciiStl("t", [{ ...tri, matrix: T }]), /vertex 10 20 30/);
});

test("several meshes go into one solid (a print plate)", () => {
  const s = toAsciiStl("plate", [{ ...tri, matrix: I }, { ...tri, matrix: I }]);
  assert.equal((s.match(/facet normal/g) || []).length, 2);
  assert.equal((s.match(/^solid /gm) || []).length, 1);
});

test("a degenerate triangle does not produce NaN", () => {
  const flat = { positions: new Float32Array([0, 0, 0, 1, 0, 0, 2, 0, 0]), index: new Uint32Array([0, 1, 2]) };
  assert.doesNotMatch(toAsciiStl("t", [{ ...flat, matrix: I }]), /NaN/);
});

import { toBinaryStl } from "../../tools/static/lib/stl.js";

test("binary STL has an 80 byte header, a count and 50 bytes per triangle", () => {
  const b = toBinaryStl([{ ...tri, matrix: I }, { ...tri, matrix: I }]);
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  assert.equal(b.length, 84 + 50 * 2);
  assert.equal(dv.getUint32(80, true), 2);
});

test("binary STL stores the normal and the transformed vertices", () => {
  const T = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 20, 30, 1];
  const b = toBinaryStl([{ ...tri, matrix: T }]);
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  assert.deepEqual([dv.getFloat32(84, true), dv.getFloat32(88, true), dv.getFloat32(92, true)], [0, 0, 1]);
  assert.deepEqual([dv.getFloat32(96, true), dv.getFloat32(100, true), dv.getFloat32(104, true)], [10, 20, 30]);
});

test("binary STL is much smaller and faster to build than ASCII for big meshes", () => {
  const n = 20000, positions = new Float32Array(n * 9), index = new Uint32Array(n * 3);
  for (let i = 0; i < n * 3; i++) { index[i] = i; positions[3 * i] = i % 97; positions[3 * i + 1] = i % 89; positions[3 * i + 2] = i % 83; }
  const m = { positions, index, matrix: I };
  toBinaryStl([m]); toAsciiStl("w", [m]);                           // warm up the JIT so the comparison is fair
  const t0 = performance.now(); const bin = toBinaryStl([m]); const tb = performance.now() - t0;
  const t1 = performance.now(); const asc = toAsciiStl("s", [m]); const ta = performance.now() - t1;
  assert.ok(bin.length < asc.length / 2);                     // short integer test coordinates; real float coordinates give ~5x
  assert.ok(tb < ta, `binary ${tb.toFixed(0)} ms vs ascii ${ta.toFixed(0)} ms`);
});
