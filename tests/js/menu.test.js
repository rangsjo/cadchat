import test from "node:test";
import assert from "node:assert/strict";
import { buildMenus, flatten, findItem } from "../../tools/static/lib/menu.js";

const base = {
  projects: [{ path: "/p/a", name: "Chairs", current: true }, { path: "/p/b", name: "Shelf", current: false }],
  library: ["shaft", "bracket"], exports: [{ name: "table_open.step" }], joints: [{ kind: "dado", label: "Dado (housing)" }],
  curModel: "table", assistant: { listening: false }, display: { grid: true, planes: false },
  displayItems: [{ key: "grid", label: "Floor grid" }, { key: "planes", label: "Section planes" }],
};
const menu = (m, name) => m.find((x) => x.label === name);

test("the bar has the conventional menus in order", () => {
  assert.deepEqual(buildMenus(base).map((m) => m.label), ["File", "View", "Tools", "Assistant", "Help"]);
});

test("File: new, recent projects, save version, import, export, settings", () => {
  const file = menu(buildMenus(base), "File");
  const ids = flatten(file.items).map((i) => i.id);
  for (const id of ["project:new", "model:new:part", "model:new:mechanism", "model:lib:shaft", "version:save", "import", "export:stl", "export:cutlist", "export:file:table_open.step", "settings"]) assert.ok(ids.includes(id), id);
  const recent = findItem(file.items, "Open recent");
  assert.equal(recent.sub.length, 2);
  assert.equal(recent.sub[0].checked, true);
  assert.equal(recent.sub[0].disabled, true);                         // you are in it
  assert.equal(recent.sub[1].id, "project:open:/p/b");
});

test("without other projects the recent list says so", () => {
  const file = menu(buildMenus({ ...base, projects: [{ path: "/p/a", name: "Chairs", current: true }] }), "File");
  const sub = findItem(file.items, "Open recent").sub;
  assert.equal(sub.length, 2);
  assert.equal(sub[1].disabled, true);
});

test("saving needs a model, exports of files only when there are some", () => {
  const file = menu(buildMenus({ ...base, curModel: null, exports: [] }), "File");
  assert.equal(findItem(file.items, "Save version…").disabled, true);
  assert.ok(!flatten(file.items).some((i) => (i.id ?? "").startsWith("export:file:")));
});

test("View lists the display switches with their state and the camera views", () => {
  const view = menu(buildMenus(base), "View");
  const grid = flatten(view.items).find((i) => i.id === "display:grid");
  const planes = flatten(view.items).find((i) => i.id === "display:planes");
  assert.equal(grid.checked, true);
  assert.equal(planes.checked, false);
  assert.ok(flatten(view.items).some((i) => i.id === "view:iso"));
});

test("Tools has the measuring tools and the joint library", () => {
  const ids = flatten(menu(buildMenus(base), "Tools").items).map((i) => i.id);
  for (const id of ["tool:measure", "tool:section", "tool:isolate", "tool:check", "joint:dado", "joints:open"]) assert.ok(ids.includes(id), id);
});

test("Assistant: start is only offered while nobody listens", () => {
  const off = flatten(menu(buildMenus(base), "Assistant").items);
  assert.equal(off.find((i) => i.id === "assistant:start").disabled, false);
  const on = flatten(menu(buildMenus({ ...base, assistant: { listening: true } }), "Assistant").items);
  assert.equal(on.find((i) => i.id === "assistant:start").disabled, true);
  assert.ok(on.some((i) => i.id === "settings"));
});

test("Help has the quick start, shortcuts and about", () => {
  const ids = flatten(menu(buildMenus(base), "Help").items).map((i) => i.id);
  for (const id of ["help:tour", "help:wizard", "help:start", "help:keys", "help:resume", "help:about"]) assert.ok(ids.includes(id), id);
});

test("every actionable item has an id and a label; ids are unique", () => {
  const all = flatten(buildMenus(base).flatMap((m) => m.items)).filter((i) => !i.sep && !i.sub);
  assert.ok(all.every((i) => i.id && i.label));
  const view = flatten(menu(buildMenus(base), "View").items);
  assert.equal(new Set(view.filter((i) => i.id).map((i) => i.id)).size, view.filter((i) => i.id).length);
});

test("View: grid has its shortcut and the detailed token usage is reachable", () => {
  const ids = flatten(menu(buildMenus(base), "View").items);
  assert.equal(ids.find((i) => i.id === "display:grid").shortcut, "G");
  assert.ok(ids.some((i) => i.id === "usage:open"));
  assert.equal(ids.filter((i) => i.id?.startsWith("view:")).length, 5);
});

test("the chat can be cleared from the Assistant menu", () => {
  assert.ok(flatten(menu(buildMenus(base), "Assistant").items).some((i) => i.id === "chat:clear"));
});
