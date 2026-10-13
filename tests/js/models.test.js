import test from "node:test";
import assert from "node:assert/strict";
import { chooseModel, publishedSince } from "../../tools/static/lib/models.js";

const list = (...ids) => ids.map((id) => ({ id, built: true }));

test("the remembered model wins if it still exists", () => {
  assert.equal(chooseModel({ models: list("a", "b"), latest: "b", stored: "a" }), "a");
});

test("otherwise the most recently published model", () => {
  assert.equal(chooseModel({ models: list("a", "b"), latest: "b", stored: "gone" }), "b");
});

test("with nothing built the first script is chosen, with nothing at all null", () => {
  assert.equal(chooseModel({ models: [{ id: "x", built: false }], latest: null, stored: null }), "x");
  assert.equal(chooseModel({ models: [], latest: null, stored: null }), null);
});

test("a model that was published again is reported, unchanged ones are not", () => {
  assert.equal(publishedSince({ a: 1, b: 2 }, { a: 1, b: 3 }), "b");
  assert.equal(publishedSince({ a: 1 }, { a: 1 }), null);
});

test("a brand new model counts as published, the first load does not", () => {
  assert.equal(publishedSince({ a: 1 }, { a: 1, c: 5 }), "c");
  assert.equal(publishedSince(null, { a: 1 }), null);
});

test("with several changes the newest stamp wins", () => {
  assert.equal(publishedSince({ a: 1, b: 1 }, { a: 5, b: 9 }), "b");
});
