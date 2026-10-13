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
