import test from "node:test";
import assert from "node:assert/strict";
import { stem, roleOf, roleColors } from "../../tools/static/lib/roles.js";

test("stem strips side and position suffixes", () => {
  assert.equal(stem("post_front_R"), "post");
  assert.equal(stem("flap_inner_L"), "flap_inner");
  assert.equal(stem("leg_3"), "leg");
  assert.equal(stem("centre_top"), "centre_top");
});

test("roleOf prefers the published role, else the first word of the stem", () => {
  assert.equal(roleOf({ name: "x", role: "leg" }), "leg");
  assert.equal(roleOf({ name: "post_front_R" }), "post");
  assert.equal(roleOf({ name: "hinge_inner_barrel_R" }), "hinge");
  assert.equal(roleOf({ name: "plate" }), "plate");
});

test("roleColors gives every role a stable, distinct colour in order of appearance", () => {
  const parts = [{ name: "leg_1" }, { name: "top_a" }, { name: "leg_2" }, { name: "x", role: "top" }];
  const c = roleColors(parts);
  assert.deepEqual([...c.keys()], ["leg", "top"]);
  assert.notEqual(c.get("leg"), c.get("top"));
  assert.deepEqual([...roleColors(parts)], [...c]);
});

test("more roles than palette colours still get colours", () => {
  const parts = Array.from({ length: 30 }, (_, i) => ({ name: `r${i}x` , role: `role${i}` }));
  assert.equal(roleColors(parts).size, 30);
});
