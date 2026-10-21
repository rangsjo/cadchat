// The menu bar as data: buildMenus(state) -> [{label, items}], an item is {id, label, shortcut?, disabled?, checked?, sub?} or {sep: true}.
// The viewer draws it and calls its action for the id; keeping it pure makes it testable.
const SEP = { sep: true };

export function flatten(items) {
  return items.flatMap((i) => (i.sub ? [i, ...flatten(i.sub)] : [i]));
}

export function findItem(items, label) {
  return flatten(items).find((i) => i.label === label);
}

export function buildMenus(s) {
  const projects = s.projects ?? [];
  const others = projects.filter((p) => !p.current);
  const item = (p) => ({ id: `project:open:${p.path}`, label: p.name, checked: !!p.current, disabled: !!p.current });
  const recent = [...projects.filter((p) => p.current), ...others].map(item);
  if (!others.length) recent.push({ label: "No other projects", disabled: true });
  const exportFiles = (s.exports ?? []).map((f) => ({ id: `export:file:${f.name}`, label: f.name }));
  const file = [
    { id: "project:new", label: "New project…" },
    { label: "New model", sub: [
      { id: "model:new:part", label: "Part" },
      { id: "model:new:mechanism", label: "Mechanism" },
      { label: "From library", sub: (s.library ?? []).map((n) => ({ id: `model:lib:${n}`, label: n })) },
    ] },
    SEP,
    { label: "Open recent", sub: recent },
    SEP,
    { id: "version:save", label: "Save version…", shortcut: "Ctrl+S", disabled: !s.curModel },
    { id: "import", label: "Import STEP/STL…" },
    { label: "Export", sub: [
      { id: "export:stl", label: "STL of this pose", disabled: !s.curModel },
      { id: "export:plates", label: "Print plates (STL)", disabled: !s.curModel },
      { id: "export:cutlist", label: "Cut list (CSV)", disabled: !s.curModel },
      { id: "export:shot", label: "Screenshot (PNG)" },
      { id: "export:site", label: "Workshop site for the phone…", disabled: !s.curModel },
      ...(exportFiles.length ? [SEP, ...exportFiles] : []),
    ] },
    SEP,
    { id: "settings", label: "Settings…" },
  ];
  const view = [
    { id: "view:iso", label: "Iso", shortcut: "1" }, { id: "view:top", label: "Top", shortcut: "2" }, { id: "view:front", label: "Front", shortcut: "3" }, { id: "view:side", label: "Side", shortcut: "4" }, { id: "view:fit", label: "Fit to window", shortcut: "F" },
    SEP,
    ...(s.displayItems ?? []).map((d) => ({ id: `display:${d.key}`, label: d.label, checked: !!(s.display ?? {})[d.key], ...(d.key === "grid" ? { shortcut: "G" } : {}) })),
    SEP,
    { id: "display:all", label: "Show all overlays", shortcut: "H" }, { id: "display:clean", label: "Model only", shortcut: "H" },
    SEP,
    { id: "usage:open", label: "Token usage…" },
  ];
  const tools = [
    { id: "tool:measure", label: "Measure", shortcut: "M" }, { id: "tool:section", label: "Section", shortcut: "S" },
    { id: "tool:isolate", label: "Isolate", shortcut: "I" }, { id: "tool:check", label: "Check collisions", disabled: !s.curModel },
    SEP,
    { label: "Joint library", sub: [...(s.joints ?? []).map((j) => ({ id: `joint:${j.kind}`, label: j.label })), SEP, { id: "joints:open", label: "Joint library…" }] },
  ];
  const assistant = [
    { id: "assistant:start", label: "Start listening", disabled: !!(s.assistant ?? {}).listening },
    { id: "chat:open", label: "Open chat" },
    { id: "chat:clear", label: "Clear chat…" },
    SEP,
    { id: "settings", label: "Agent settings…" },
  ];
  const help = [
    { id: "help:tour", label: "What can cadchat do?" }, { id: "help:wizard", label: "Set up the AI assistant…" }, { id: "help:start", label: "Quick start" }, { id: "help:keys", label: "Keyboard shortcuts" }, { id: "help:resume", label: "Coming back after a break" },
    SEP,
    { id: "help:about", label: "About cadchat" },
  ];
  return [{ label: "File", items: file }, { label: "View", items: view }, { label: "Tools", items: tools }, { label: "Assistant", items: assistant }, { label: "Help", items: help }];
}
