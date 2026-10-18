import test from "node:test";
import assert from "node:assert/strict";
import { DISPLAY_ITEMS, defaultDisplay, loadDisplay, saveDisplay, toggled, preset } from "../../tools/static/lib/display.js";

test("every overlay can be switched, and all start on", () => {
  const keys = DISPLAY_ITEMS.map((i) => i.key);
  for (const k of ["grid", "planes", "axes", "links", "jointLabels", "dims", "info", "badge"]) assert.ok(keys.includes(k), k);
  assert.ok(Object.values(defaultDisplay()).every((v) => v === true));
  assert.ok(DISPLAY_ITEMS.every((i) => i.label && i.key));
});

test("toggled flips one switch and leaves the state untouched", () => {
  const s = defaultDisplay();
  const t = toggled(s, "planes");
  assert.equal(t.planes, false);
  assert.equal(s.planes, true);
  assert.equal(t.grid, true);
  assert.throws(() => toggled(s, "nope"));
});

test("saved state round-trips and tolerates garbage", () => {
  const s = toggled(defaultDisplay(), "grid");
  assert.deepEqual(loadDisplay(saveDisplay(s)), s);
  assert.deepEqual(loadDisplay(null), defaultDisplay());
  assert.deepEqual(loadDisplay("{broken"), defaultDisplay());
  assert.deepEqual(loadDisplay('{"grid":"yes","bogus":false,"axes":false}'), { ...defaultDisplay(), axes: false });
});

test("presets: all shows everything, clean shows only the model", () => {
  assert.deepEqual(preset("all"), defaultDisplay());
  const c = preset("clean");
  assert.ok(Object.values(c).every((v) => v === false));
  assert.throws(() => preset("weird"));
});

test("measurements stay visible while measuring even when the dimension labels are switched off", async () => {
  const { overlayVisible } = await import("../../tools/static/lib/display.js");
  const off = toggled(defaultDisplay(), "dims");
  assert.equal(overlayVisible(off, false), false);
  assert.equal(overlayVisible(off, true), true);
  assert.equal(overlayVisible(defaultDisplay(), false), true);
});
