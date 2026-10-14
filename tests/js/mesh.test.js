import test from "node:test";
import assert from "node:assert/strict";
import { decodeMesh } from "../../tools/static/lib/mesh.js";

const b64 = (typed) => Buffer.from(typed.buffer, typed.byteOffset, typed.byteLength).toString("base64");

test("decodes base64 float32 positions and uint32 indices", () => {
  const v = new Float32Array([0, 0, 0, 1.5, -2, 3]), t = new Uint32Array([0, 1, 0]);
  const m = decodeMesh(b64(v), b64(t));
  assert.deepEqual([...m.positions], [...v]);
  assert.deepEqual([...m.index], [...t]);
  assert.ok(m.positions instanceof Float32Array && m.index instanceof Uint32Array);
});

test("an empty mesh decodes to empty arrays", () => {
  const m = decodeMesh("", "");
  assert.equal(m.positions.length, 0);
  assert.equal(m.index.length, 0);
});

test("large meshes decode without copying through JSON", () => {
  const v = new Float32Array(3_000_000).map((_, i) => i % 1000), t = new Uint32Array(3_000_000).map((_, i) => i);
  const s = performance.now();
  const m = decodeMesh(b64(v), b64(t));
  assert.equal(m.positions.length, 3_000_000);
  assert.ok(performance.now() - s < 500);
});
