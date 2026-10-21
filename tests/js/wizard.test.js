import test from "node:test";
import assert from "node:assert/strict";
import { TOUR, recommendProvider, recommendedMode, needsWizard, summary, canContinue } from "../../tools/static/lib/wizard.js";

const providers = [
  { id: "claude", name: "Claude Code", listens: true }, { id: "copilot", name: "GitHub Copilot CLI", listens: false },
  { id: "codex", name: "OpenAI Codex CLI", listens: false }, { id: "custom", name: "Another agent", listens: false },
];

test("the tour says what the project can do for you, one short slide each", () => {
  assert.ok(TOUR.length >= 5 && TOUR.length <= 8);
  const all = TOUR.map((s) => `${s.title} ${s.text}`).join(" ").toLowerCase();
  for (const word of ["model", "chat", "measure", "cut list", "phone", "history", "joint"]) assert.ok(all.includes(word), word);
  assert.ok(TOUR.every((s) => s.title && s.text.length < 260));
});

test("the first installed agent is recommended, Claude Code when none is found", () => {
  assert.equal(recommendProvider(providers, { copilot: { installed: true }, codex: { installed: true } }), "copilot");
  assert.equal(recommendProvider(providers, { claude: { installed: true }, copilot: { installed: true } }), "claude");
  assert.equal(recommendProvider(providers, {}), "claude");
  assert.equal(recommendProvider(providers, { custom: { installed: true } }), "claude");              // a custom command is never auto-picked
});

test("agents that keep a live watch can run as a session, the others answer message by message", () => {
  assert.equal(recommendedMode(providers[0]), "session");
  assert.equal(recommendedMode(providers[1]), "message");
  assert.equal(recommendedMode(providers[3]), "message");
});

test("the wizard shows on the first start only, and never while an assistant is already listening", () => {
  assert.equal(needsWizard({ setup_done: false }, { listening: false }), true);
  assert.equal(needsWizard({ setup_done: true }, { listening: false }), false);
  assert.equal(needsWizard({ setup_done: false }, { listening: true }), false);
});

test("the summary names the agent and what happens on each chat message", () => {
  assert.match(summary(providers[1], "message", {}), /GitHub Copilot CLI.*once per message/i);
  assert.match(summary(providers[0], "session", {}), /Claude Code.*live session/i);
  assert.match(summary(providers[3], "message", { command: "myagent --x" }), /myagent --x/);
});

test("a custom agent needs a command before the wizard can go on", () => {
  assert.equal(canContinue({ id: "custom" }, ""), false);
  assert.equal(canContinue({ id: "custom" }, "myagent"), true);
  assert.equal(canContinue({ id: "claude" }, ""), true);
});
