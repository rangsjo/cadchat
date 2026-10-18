import test from "node:test";
import assert from "node:assert/strict";
import { fmtTokens, lastDays, scale, badgeText, barSegments } from "../../tools/static/lib/usage.js";

test("token counts are short: 1.1k, 134k, 1.2M", () => {
  assert.equal(fmtTokens(0), "0");
  assert.equal(fmtTokens(812), "812");
  assert.equal(fmtTokens(1126), "1.1k");
  assert.equal(fmtTokens(9500), "9.5k");
  assert.equal(fmtTokens(9999), "10k");
  assert.equal(fmtTokens(133710), "134k");
  assert.equal(fmtTokens(990996), "991k");
  assert.equal(fmtTokens(1234567), "1.2M");
  assert.equal(fmtTokens(212708985), "213M");
});

test("lastDays gives exactly n days ending at the given date, zero filled", () => {
  const days = [{ date: "2026-10-15", output: 5 }, { date: "2026-10-18", output: 9 }];
  const r = lastDays(days, 5, "2026-10-18");
  assert.deepEqual(r.map((d) => d.date), ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18"]);
  assert.deepEqual(r.map((d) => d.output), [0, 5, 0, 0, 9]);
  assert.equal(lastDays([], 3, "2026-03-01")[0].date, "2026-02-27");           // across a month end
});

test("scale maps values to 0..1 against the largest, all zero stays zero", () => {
  assert.deepEqual(scale([0, 5, 10]), [0, 0.5, 1]);
  assert.deepEqual(scale([0, 0]), [0, 0]);
});

test("the small badge says what was written today and how much came from the cache", () => {
  const r = { today: { output: 133710, input: 170, cache_read: 37404959, cache_creation: 185775, messages: 85 }, cache_share: 0.995, sources: 1 };
  assert.equal(badgeText(r), "134k out today · 99% cached");
  assert.equal(badgeText({ today: { output: 0, messages: 0 }, cache_share: 0, sources: 0 }), "no assistant usage found");
  assert.equal(badgeText({ today: { output: 0, messages: 0 }, cache_share: 0.5, sources: 2 }), "0 out today");
});

test("stacked bar segments are proportional to the tallest day", () => {
  const segs = barSegments({ output: 50, input: 10, cache_creation: 40, cache_read: 900 }, 1000, 100);
  assert.equal(segs.reduce((a, s) => a + s.h, 0), 100);
  assert.deepEqual(segs.map((s) => s.kind), ["output", "new", "cache"]);
  assert.deepEqual(segs.map((s) => s.h), [5, 5, 90]);
});
