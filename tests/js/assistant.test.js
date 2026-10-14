import test from "node:test";
import assert from "node:assert/strict";
import { presence, ago, stateLabel } from "../../tools/static/lib/assistant.js";

test("listening shows a green status and how long it has been listening", () => {
  const p = presence({ listening: true, since: 940, last_seen: 1000, pending: 0 }, 1000);
  assert.equal(p.level, "ok");
  assert.match(p.text, /listening/i);
});

test("not listening says when it was last seen and that messages are kept", () => {
  const p = presence({ listening: false, last_seen: 400, pending: 2 }, 1000);
  assert.equal(p.level, "off");
  assert.match(p.text, /10 min ago/);
  assert.match(p.detail, /2 .*waiting/);
});

test("never seen is its own message", () => {
  const p = presence({ listening: false, last_seen: null, pending: 0 }, 1000);
  assert.match(p.text, /not connected|never/i);
});

test("ago formats seconds, minutes, hours and days", () => {
  assert.equal(ago(5), "just now");
  assert.equal(ago(59), "just now");
  assert.equal(ago(90), "1 min ago");
  assert.equal(ago(3600 * 3), "3 h ago");
  assert.equal(ago(86400 * 2), "2 days ago");
});

test("delivery states have short labels", () => {
  assert.equal(stateLabel("queued"), "sent");
  assert.equal(stateLabel("seen"), "seen");
  assert.equal(stateLabel("working"), "working on it");
  assert.equal(stateLabel("answered"), "");
  assert.equal(stateLabel(undefined), "");
});
